# -*- coding: utf-8 -*-
"""
momo 限時搶購 - 商品資料抓取程式 v10

v10 新增內容（2026/10）：
  - 開檔資料改為「提前抓」：每次 open（以及 close）執行時，順便把
    「下一檔」的商品與數量先存成下一檔的 _open.csv。
    例如 11:03 就先存好 14:00 檔的開檔資料，避免大活動開搶第一分鐘
    就被秒殺、開檔後才抓會抓不到原始數量。
    close（結束前5分）會再更新一次，讓數字更接近真正開檔前的狀態。
  - 開檔後 3 分鐘的 open 執行改為「補抓」：只有提前抓的資料裡數量
    是 0 或空白的商品、以及提前抓時還沒出現的商品，才用這次的資料補上；
    如果完全沒有提前抓到（例如跨日的 00:00 檔），就照舊整檔重抓。
  - 修正數量解析：「倒數：1,951組」以前只會讀到 1，現在正確讀成 1951
  - 當檔區塊改用頁面上的時段文字比對，找不到才退回用第 1 個區塊
  - 快照多一欄 source：pre = 提前抓、open = 開檔後抓

v9 新增內容：
  - 抓取失敗自動記錄：當頁面載入逾時（重試後仍失敗）、找不到
    .MENTAL 區塊、或發生其他預期外錯誤時，會將失敗事件記錄到
    snapshots/scrape_failures.csv，方便之後離線檢視追蹤穩定性，
    不需要每次都去 log 檔案裡翻找。
  - 記錄欄位：timestamp（記錄時間）、date（時段日期）、
    slot（時段代碼）、checkpoint（open/mid/close）、reason（原因）

沿用 v8 修正內容：
  - page.goto 加上重試機制（逾時45秒，最多重試2次）
  - date_str 在 run() 一開始就固定，避免跨午夜日期錯位

沿用先前版本邏輯：
  - 每次執行只抓「當前時段」一筆資料，checkpoint 參數決定
    這次是 open（開檔）/ mid（時段中點）/ close（結束前5分）
  - CLOSE 抓取邏輯：直接用 .MENTAL 區塊第1個（mentals[0]）
    作為當前時段，不依賴已失效的 #posTag1

執行方式：
  python momo_scraper.py open
  python momo_scraper.py mid
  python momo_scraper.py close
"""

import re
import sys
import csv
import os
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

TW_TZ      = timezone(timedelta(hours=8))
MOMO_URL   = "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O1K5FBOqsvN&n=1"
OUTPUT_DIR = "snapshots"
FAILURE_LOG = os.path.join(OUTPUT_DIR, "scrape_failures.csv")

VALID_CHECKPOINTS = ("open", "mid", "close")

GOTO_TIMEOUT_MS = 45000   # 頁面載入逾時時間
MAX_RETRIES     = 2       # 最多重試 2 次（總共嘗試 3 次）
RETRY_WAIT_MS   = 5000    # 每次重試前等待 5 秒

# 哪些檢查點要順便提前抓「下一檔」的開檔資料
PRECAPTURE_AT = ("open", "close")

FIELDNAMES = ["icode","brand","name","discount","old_price","price","qty","scraped_at","source"]

SLOTS = [
    (0,  7,  "0000"),
    (7,  11, "0700"),
    (11, 14, "1100"),
    (14, 18, "1400"),
    (18, 22, "1800"),
    (22, 24, "2200"),
]


def get_current_slot() -> str:
    now_hour = datetime.now(TW_TZ).hour
    for start, end, slot in SLOTS:
        if start <= now_hour < end:
            return slot
    return "2200"


def next_slot_of(slot_code: str, date_str: str):
    """回傳下一檔的 (時段代碼, 日期)。22:00 的下一檔是隔天的 00:00"""
    codes = [s[2] for s in SLOTS]
    idx = codes.index(slot_code)
    if idx + 1 < len(codes):
        return codes[idx + 1], date_str
    next_day = datetime.strptime(date_str, "%Y%m%d") + timedelta(days=1)
    return codes[0], next_day.strftime("%Y%m%d")


def find_block(mentals, slot_code: str):
    """用區塊上的時段文字（例如「本檔時段 14:00 開搶」）找出指定時段的區塊"""
    label = f"{slot_code[:2]}:{slot_code[2:]}"
    for div in mentals:
        try:
            el = div.query_selector(".time")
            text = el.inner_text() if el else ""
        except Exception:
            text = ""
        if label in text:
            return div
    return None


def snapshot_path(date_str: str, slot_code: str, checkpoint: str) -> str:
    return os.path.join(OUTPUT_DIR, f"momo_{date_str}_{slot_code}_{checkpoint}.csv")


def load_snapshot_rows(filepath: str) -> list:
    if not os.path.exists(filepath):
        return []
    with open(filepath, encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if r.get("icode")]


def qty_missing(value) -> bool:
    """數量是空白或 0，視為需要補抓"""
    text = str(value).strip() if value is not None else ""
    return text == "" or text == "0"


def merge_open(pre_rows: list, fresh: list):
    """提前抓的資料為主，只補數量為 0/空白的商品，以及新出現的商品"""
    fresh_map = {p["icode"]: p for p in fresh}
    merged, filled, added = [], 0, 0
    seen = set()
    for row in pre_rows:
        icode = row["icode"]
        seen.add(icode)
        if qty_missing(row.get("qty")) and icode in fresh_map and not qty_missing(fresh_map[icode].get("qty")):
            merged.append(fresh_map[icode])
            filled += 1
        else:
            row.setdefault("source", "pre")
            merged.append(row)
    for p in fresh:
        if p["icode"] not in seen:
            merged.append(p)
            added += 1
    return merged, filled, added


def log_failure(date_str: str, slot_code: str, checkpoint: str, reason: str):
    """把抓取失敗事件記錄到 snapshots/scrape_failures.csv，方便之後離線查看"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_exists = os.path.exists(FAILURE_LOG)
    now = datetime.now(TW_TZ)
    with open(FAILURE_LOG, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "date", "slot", "checkpoint", "reason"])
        writer.writerow([now.strftime("%Y-%m-%d %H:%M:%S"), date_str, slot_code, checkpoint, reason])
    print(f"  📝 已記錄失敗事件 → {FAILURE_LOG}（原因：{reason}）")


def parse_items(items, scraped_at: str, source: str = "open") -> list:
    products = []
    for li in items:
        try:
            a_tag = li.query_selector("a[href]")
            href  = a_tag.get_attribute("href") if a_tag else ""
            m     = re.search(r"i_code=(\d+)", href or "")
            icode = m.group(1) if m else None
            if not icode:
                continue

            def get_txt(sel):
                el = li.query_selector(sel)
                return el.inner_text().strip() if el else ""

            # 「倒數：1,951組」要先拿掉千分位逗號再取數字
            qty_match = re.search(r"(\d+)", get_txt(".last").replace(",", "").replace("，", ""))
            qty       = int(qty_match.group(1)) if qty_match else None

            old_price = get_txt(".oldPrice")
            price     = get_txt(".price")

            products.append({
                "icode":      icode,
                "brand":      get_txt(".brand"),
                "name":       get_txt(".brand2"),
                "discount":   get_txt(".discount"),
                "old_price":  re.sub(r"[^\d]", "", old_price) or None,
                "price":      re.sub(r"[^\d]", "", price)     or None,
                "qty":        qty,
                "scraped_at": scraped_at,
                "source":     source,
            })
        except Exception as e:
            print(f"  ⚠️ 跳過商品：{e}")

    seen = {}
    for p in products:
        seen[p["icode"]] = p
    return list(seen.values())


def save_csv(products: list, date_str: str, slot_code: str, checkpoint: str, time_text: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    filename = f"momo_{date_str}_{slot_code}_{checkpoint}.csv"
    filepath = os.path.join(OUTPUT_DIR, filename)

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(products)

    print(f"  ✅ {checkpoint.upper()} → {filename}（{len(products)} 個商品）{time_text}")
    return filepath


def goto_with_retry(page, url: str):
    """帶重試機制的頁面載入，應對開檔瞬間流量尖峰造成的逾時"""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
            return True, None
        except Exception as e:
            last_error = type(e).__name__
            if attempt <= MAX_RETRIES:
                print(f"  ⚠️ 第{attempt}次頁面載入失敗，{RETRY_WAIT_MS//1000}秒後重試...（{last_error}）")
                page.wait_for_timeout(RETRY_WAIT_MS)
            else:
                print(f"  ❌ 頁面載入失敗，已重試{MAX_RETRIES}次仍無法載入，放棄本次抓取（{last_error}）")
    return False, last_error


def run(checkpoint: str):
    now        = datetime.now(TW_TZ)
    scraped_at = now.strftime("%Y-%m-%d %H:%M:%S")
    date_str   = now.strftime("%Y%m%d")   # 一開始就固定，全流程共用，避免跨午夜錯位
    cur_slot   = get_current_slot()

    print(f"\n🚀 開始抓取（台灣時間 {now.strftime('%H:%M')}，checkpoint={checkpoint}）")
    print(f"   當前時段：{cur_slot}")

    products  = []
    time_text = ""
    next_products = []
    next_slot, next_date = next_slot_of(cur_slot, date_str)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page    = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )

            print(f"  開啟頁面：{MOMO_URL}")
            ok, err_reason = goto_with_retry(page, MOMO_URL)

            if not ok:
                log_failure(date_str, cur_slot, checkpoint, f"page_goto_failed:{err_reason}")
            else:
                try:
                    page.wait_for_selector("#CustExclbuy div.MENTAL", timeout=15000)
                except Exception:
                    print("  ⚠️ 等待頁面逾時，繼續嘗試...")
                page.wait_for_timeout(3000)

                # 抓取所有 .MENTAL 區塊；先用時段文字找當前時段，找不到才用第1個
                mentals = page.query_selector_all("#CustExclbuy div.MENTAL")

                if len(mentals) >= 1:
                    cur_div     = find_block(mentals, cur_slot) or mentals[0]
                    time_el_cur = cur_div.query_selector(".time")
                    time_text   = time_el_cur.inner_text().strip() if time_el_cur else ""
                    items       = cur_div.query_selector_all("li.box1")
                    products    = parse_items(items, scraped_at)
                    if len(products) == 0:
                        log_failure(date_str, cur_slot, checkpoint, "mentals_found_but_zero_products")
                else:
                    print("  ⚠️ 找不到當前時段區塊")
                    log_failure(date_str, cur_slot, checkpoint, "no_mentals_found")

                # 順便提前抓「下一檔」的開檔資料
                if checkpoint in PRECAPTURE_AT:
                    next_div = find_block(mentals, next_slot)
                    if next_div is not None:
                        next_products = parse_items(next_div.query_selector_all("li.box1"), scraped_at, source="pre")

            browser.close()

    except Exception as e:
        print(f"  ❌ 發生預期外錯誤：{type(e).__name__}: {e}")
        log_failure(date_str, cur_slot, checkpoint, f"unexpected_error:{type(e).__name__}")

    print()
    if checkpoint == "open":
        # 開檔：若已有提前抓的資料，只補數量為 0/空白與新出現的商品
        pre_rows = load_snapshot_rows(snapshot_path(date_str, cur_slot, "open"))
        if pre_rows:
            merged, filled, added = merge_open(pre_rows, products)
            print(f"  📦 已有提前抓的開檔資料 {len(pre_rows)} 個商品 → 補抓數量 {filled} 個、新增商品 {added} 個")
            save_csv(merged, date_str, cur_slot, checkpoint, f"  ← {time_text}")
        else:
            print("  📦 沒有提前抓的開檔資料，改用這次抓到的整檔資料")
            save_csv(products, date_str, cur_slot, checkpoint, f"  ← {time_text}")
    else:
        save_csv(products, date_str, cur_slot, checkpoint, f"  ← {time_text}")

    # 存下一檔的提前開檔資料（已經有開檔後資料的檔案不覆蓋；抓不到就保留舊的）
    if checkpoint in PRECAPTURE_AT:
        next_path = snapshot_path(next_date, next_slot, "open")
        existing = load_snapshot_rows(next_path)
        if not next_products:
            print(f"  ⏭️ 頁面上還沒有下一檔（{next_slot}）的資料，開檔後再抓")
        elif any(r.get("source") == "open" for r in existing):
            print(f"  ⏭️ 下一檔（{next_slot}）已有開檔後資料，不覆蓋")
        else:
            print(f"  🔮 提前抓下一檔（{next_slot}）開檔資料：")
            save_csv(next_products, next_date, next_slot, "open", "")

    return cur_slot


if __name__ == "__main__":
    checkpoint = sys.argv[1] if len(sys.argv) > 1 else "close"
    if checkpoint not in VALID_CHECKPOINTS:
        print(f"❌ 無效的 checkpoint 參數：{checkpoint}（必須是 open / mid / close）")
        sys.exit(1)
    run(checkpoint)
