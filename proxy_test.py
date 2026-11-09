#!/usr/bin/env python3
"""proxy_test.py - 檢查代理能不能連到 momo 活動頁（只讀取，不寫任何資料）
用法: python3 proxy_test.py
"""
import proxy_config
from playwright.sync_api import sync_playwright

URL = "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O1K5FBOqsvN&n=1"
px = proxy_config.load()
print("代理：", (px or {}).get("server", "未設定（直接連線）"))
size = {"bytes": 0}
with sync_playwright() as p:
    b, pg = proxy_config.open_page(p)
    def on_resp(r):
        try:
            size["bytes"] += int(r.headers.get("content-length", 0))
        except Exception:
            pass
    pg.on("response", on_resp)
    try:
        pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(6000)
        print("標題：", pg.title())
        print("MENTAL 區塊數：", len(pg.query_selector_all("#CustExclbuy div.MENTAL")))
        print("約傳輸量：%.2f MB" % (size["bytes"] / 1e6))
    except Exception as e:
        print("❌ 連線失敗：", type(e).__name__, e)
    b.close()
