# -*- coding: utf-8 -*-
"""
momo 第一層分類批次抓取工具

針對資料庫裡累積的商品，逐一訪問商品詳情頁，抓取 momo 官方的第一層
分類（不是自訂的AI/規則式分類，是momo網站本身標示的分類）。

抓取邏輯（2026/08 實測驗證）：
  商品詳情頁的麵包屑導覽，是一個 class 包含 "gap-x-1" 的容器，
  裡面第一個連結的文字，就是該商品的 momo 第一層分類。
  這跟頁面上方那份「全站導覽選單」(32個分類都用同一種class)不同，
  麵包屑元素的 class 帶有 "first:text-" 這種樣式，用來標示目前分類。

手動觸發，不掛進 crontab，只處理「尚未抓過分類」的新商品。
準確度不要求100%，能抓到大部分即可。

執行方式：
  python3 fetch_momo_categories.py
"""

import csv
import os
import time
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

TW_TZ = timezone(timedelta(hours=8))
OUTPUT_DIR = "snapshots"
ALL_RESULTS = os.path.join(OUTPUT_DIR, "all_results.csv")
CATEGORIES_FILE = os.path.join(OUTPUT_DIR, "momo_categories.csv")
DETAIL_URL_TMPL = "https://www.momoshop.com.tw/goods/GoodsDetail.jsp?i_code={icode}"

WAIT_BETWEEN_REQUESTS_SEC = 2  # 每個商品之間稍微等一下，避免對momo發太密集的請求


def load_all_products() -> dict:
    products = {}
    if not os.path.exists(ALL_RESULTS):
        return products
    with open(ALL_RESULTS, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            icode = row.get("icode")
            if icode:
                products[icode] = row.get("name", "")
    return products


def load_existing_categories() -> set:
    existing = set()
    if not os.path.exists(CATEGORIES_FILE):
        return existing
    with open(CATEGORIES_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("icode"):
                existing.add(row["icode"])
    return existing


def append_categories(new_rows: list):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_exists = os.path.exists(CATEGORIES_FILE)
    fieldnames = ["icode", "product_name", "momo_category_l1", "status", "updated_at"]
    with open(CATEGORIES_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(new_rows)


def fetch_category(page, icode: str):
    """回傳 (分類文字或None, 狀態說明)"""
    url = DETAIL_URL_TMPL.format(icode=icode)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2500)
    except Exception as e:
        return None, f"頁面載入失敗:{type(e).__name__}"

    try:
        result = page.evaluate("""
        () => {
            const els = document.querySelectorAll('div,ul,nav');
            for (const el of els) {
                if (el.className && el.className.includes && el.className.includes('gap-x-1')) {
                    const links = Array.from(el.querySelectorAll('a')).map(a => a.textContent.trim());
                    if (links.length > 0) return links[0];
                }
            }
            return null;
        }
        """)
    except Exception as e:
        return None, f"擷取失敗:{type(e).__name__}"

    if not result:
        return None, "找不到麵包屑元素"
    return result, "成功"


def run():
    products = load_all_products()
    existing = load_existing_categories()
    new_icodes = [i for i in products if i not in existing]

    if not new_icodes:
        print("📋 沒有新商品需要抓取分類")
        return

    print(f"🔍 發現 {len(new_icodes)} 個新商品，開始抓取 momo 第一層分類...\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )

        new_rows = []
        success_count = 0
        for idx, icode in enumerate(new_icodes, 1):
            name = products[icode]
            category, status = fetch_category(page, icode)
            now = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
            new_rows.append({
                "icode": icode,
                "product_name": name,
                "momo_category_l1": category or "",
                "status": status,
                "updated_at": now,
            })
            if category:
                success_count += 1
                print(f"  [{idx}/{len(new_icodes)}] ✅ {name[:20]} → {category}")
            else:
                print(f"  [{idx}/{len(new_icodes)}] ⚠️ {name[:20]} → {status}")

            time.sleep(WAIT_BETWEEN_REQUESTS_SEC)

        browser.close()

    append_categories(new_rows)
    print(f"\n✅ 完成，共處理 {len(new_rows)} 個商品，成功抓到分類 {success_count} 個 → {CATEGORIES_FILE}")


if __name__ == "__main__":
    run()
