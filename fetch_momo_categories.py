# -*- coding: utf-8 -*-
"""
momo 商品分類抓取程式 v2（大類 + 中類）

v2 改動（2026/10）：
  - 改讀商品頁內嵌的結構化資料（JSON-LD BreadcrumbList），
    不再解析畫面上的麵包屑樣式，比 v1 穩定
  - 一次取得「大類」與「中類」兩層，連同 momo 的分類代碼
    品牌旗艦館的商品：大類 = 品牌旗艦，中類 = 品牌名（照 momo 原樣）
  - 只處理「當檔」商品：讀最新一份 *_open.csv，只查對照表裡還沒有的品號
  - 分類對照表 snapshots/momo_categories.csv：品號查過一次就不再查
  - 失敗自動重試（5 秒 / 15 秒 / 45 秒），每筆間隔 2~4 秒隨機
  - 仍失敗的記到 snapshots/momo_category_failures.csv，之後自動補抓，
    同一品號累計失敗 3 次就不再嘗試
  - 每次順便補抓少量歷史商品（BACKFILL_PER_RUN），慢慢把舊資料補齊

執行方式：
  python3 fetch_momo_categories.py            # 當檔新商品 + 少量歷史補抓
  python3 fetch_momo_categories.py --no-backfill   # 只抓當檔新商品
"""

import csv
import os
import re
import sys
import time
import random
from glob import glob
from datetime import datetime, timezone, timedelta

TW_TZ = timezone(timedelta(hours=8))
OUTPUT_DIR = "snapshots"
ALL_RESULTS = os.path.join(OUTPUT_DIR, "all_results.csv")
CATEGORIES_FILE = os.path.join(OUTPUT_DIR, "momo_categories.csv")
FAILURES_FILE = os.path.join(OUTPUT_DIR, "momo_category_failures.csv")
MOMO_URL = "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O1K5FBOqsvN&n=1"

# 注意：product_name 放最後一欄，analysis.html 是用逗號直接切欄位，
# 品名裡若有逗號也不會影響前面的分類欄位
CAT_FIELDS = ["icode", "cat_l1", "cat_l1_code", "cat_l2", "cat_l2_code",
              "updated_at", "product_name"]
FAIL_FIELDS = ["timestamp", "icode", "reason"]

BACKFILL_PER_RUN = 20      # 每次順便補抓幾筆歷史商品（設 0 就不補）
MAX_PER_RUN = 70           # 單次執行最多查幾個商品頁（保險上限）
WAIT_MIN_SEC, WAIT_MAX_SEC = 2.0, 4.0
RETRY_WAITS_SEC = [5, 15, 45]
MAX_FAIL_RUNS = 3          # 同一品號累計失敗幾次後就放棄

# 在 momo 頁面內執行：用同一個瀏覽器工作階段去讀商品頁，取出麵包屑
FETCH_JS = r"""
async (icode) => {
  try {
    const r = await fetch('/goods/GoodsDetail.jsp?i_code=' + icode, {credentials: 'include'});
    const t = await r.text();
    const m = t.match(/"@type":\s*"BreadcrumbList"[\s\S]*?"itemListElement":\s*(\[[\s\S]*?\])\s*\}/);
    if (!m) return {status: r.status, crumbs: null};
    const list = JSON.parse(m[1]);
    return {status: r.status, crumbs: list.map(x => ({name: x.name || '', item: x.item || ''}))};
  } catch (e) {
    return {status: 0, crumbs: null, error: String(e)};
  }
}
"""


def clean(text: str) -> str:
    """分類名稱裡的半形逗號換成全形，避免打亂 CSV 欄位"""
    return (text or "").strip().replace(",", "，")


def parse_crumbs(crumbs):
    """把麵包屑轉成 (大類, 大類代碼, 中類, 中類代碼)；資料不足回傳 None"""
    if not crumbs or len(crumbs) < 2:
        return None

    def code_of(item):
        m = re.search(r"_code=(\d+)", item or "")
        return m.group(1) if m else ""

    l1, l2 = crumbs[0], crumbs[1]
    if not l1.get("name") or not l2.get("name"):
        return None
    return (clean(l1["name"]), code_of(l1.get("item")),
            clean(l2["name"]), code_of(l2.get("item")))


def load_categories() -> dict:
    cats = {}
    if os.path.exists(CATEGORIES_FILE):
        with open(CATEGORIES_FILE, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("icode") and row.get("cat_l1"):
                    cats[row["icode"]] = row
    return cats


def save_categories(cats: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tmp = CATEGORIES_FILE + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CAT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for icode in sorted(cats, key=lambda x: int(x) if x.isdigit() else 0):
            writer.writerow(cats[icode])
    os.replace(tmp, CATEGORIES_FILE)


def load_fail_counts() -> dict:
    counts = {}
    if os.path.exists(FAILURES_FILE):
        with open(FAILURES_FILE, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("icode"):
                    counts[row["icode"]] = counts.get(row["icode"], 0) + 1
    return counts


def log_failure(icode: str, reason: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    exists = os.path.exists(FAILURES_FILE)
    with open(FAILURES_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FAIL_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "icode": icode, "reason": reason,
        })


def current_slot_products() -> dict:
    """讀最新 3 份開檔快照（當檔 + 已提前抓的下一檔），回傳 {品號: 品名}"""
    opens = sorted(glob(os.path.join(OUTPUT_DIR, "momo_*_open.csv")))[-3:]
    products = {}
    for path in reversed(opens):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("icode") and row["icode"] not in products:
                    products[row["icode"]] = f"{row.get('brand', '')} {row.get('name', '')}".strip()
    if opens:
        print(f"📂 開檔快照：{'、'.join(os.path.basename(o) for o in opens)}（共 {len(products)} 個商品）")
    return products


def history_products() -> dict:
    """歷史資料裡的商品，新的排前面，回傳 {品號: 品名}"""
    products = {}
    if not os.path.exists(ALL_RESULTS):
        return products
    with open(ALL_RESULTS, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for row in reversed(rows):
        icode = row.get("icode")
        if icode and icode not in products:
            products[icode] = f"{row.get('brand', '')} {row.get('name', '')}".strip()
    return products


def build_todo(cats: dict, fail_counts: dict, backfill: int) -> list:
    """決定這次要查哪些品號：當檔新商品優先，再加少量歷史補抓"""
    def needed(icode):
        return icode not in cats and fail_counts.get(icode, 0) < MAX_FAIL_RUNS

    todo = [(i, n) for i, n in current_slot_products().items() if needed(i)]
    new_count = len(todo)
    picked = {i for i, _ in todo}

    backlog = [(i, n) for i, n in history_products().items()
               if needed(i) and i not in picked]
    todo += backlog[:max(backfill, 0)]
    todo = todo[:MAX_PER_RUN]

    print(f"🔍 當檔新商品 {new_count} 個、歷史待補 {len(backlog)} 個 → 這次查 {len(todo)} 個")
    return todo


def fetch_one(page, icode: str):
    """查一個品號，含重試。回傳 (分類tuple或None, 失敗原因)"""
    reason = ""
    for attempt in range(len(RETRY_WAITS_SEC) + 1):
        if attempt > 0:
            time.sleep(RETRY_WAITS_SEC[attempt - 1])
        try:
            res = page.evaluate(FETCH_JS, icode)
        except Exception as e:
            reason = f"執行失敗:{type(e).__name__}"
            continue
        parsed = parse_crumbs(res.get("crumbs"))
        if parsed:
            return parsed, ""
        reason = f"無分類資料(http {res.get('status')})"
        if res.get("status") in (403, 429):
            # 被擋了就不要再硬試，直接結束這個品號
            return None, f"被拒絕(http {res.get('status')})"
    return None, reason


def run(backfill: int):
    cats = load_categories()
    fail_counts = load_fail_counts()
    todo = build_todo(cats, fail_counts, backfill)
    if not todo:
        print("📋 沒有需要抓分類的商品")
        return

    from playwright.sync_api import sync_playwright

    ok_count, fail_count, blocked = 0, 0, 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        try:
            page.goto(MOMO_URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"❌ momo 頁面載入失敗，這次先不抓分類（{type(e).__name__}）")
            browser.close()
            return

        for idx, (icode, name) in enumerate(todo, 1):
            parsed, reason = fetch_one(page, icode)
            if parsed:
                l1, l1c, l2, l2c = parsed
                cats[icode] = {
                    "icode": icode, "cat_l1": l1, "cat_l1_code": l1c,
                    "cat_l2": l2, "cat_l2_code": l2c,
                    "updated_at": datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                    "product_name": name,
                }
                ok_count += 1
                blocked = 0
                print(f"  [{idx}/{len(todo)}] ✅ {name[:20]} → {l1} / {l2}")
            else:
                fail_count += 1
                log_failure(icode, reason)
                print(f"  [{idx}/{len(todo)}] ⚠️ {name[:20]} → {reason}")
                if reason.startswith("被拒絕"):
                    blocked += 1
                    if blocked >= 3:
                        print("  🛑 連續 3 筆被 momo 拒絕，提早結束，下一檔再試")
                        break

            if idx % 10 == 0:
                save_categories(cats)   # 每 10 筆存一次，中途當掉也不會白抓
            time.sleep(random.uniform(WAIT_MIN_SEC, WAIT_MAX_SEC))

        browser.close()

    save_categories(cats)
    print(f"\n✅ 完成：成功 {ok_count}、失敗 {fail_count}，對照表共 {len(cats)} 個品號 → {CATEGORIES_FILE}")


if __name__ == "__main__":
    run(0 if "--no-backfill" in sys.argv else BACKFILL_PER_RUN)
