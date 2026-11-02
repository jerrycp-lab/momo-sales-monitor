import sys
from playwright.sync_api import sync_playwright

icode = sys.argv[1]
url = f"https://www.momoshop.com.tw/goods/GoodsDetail.jsp?i_code={icode}"
print("URL:", url)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    try:
        pg.goto(url, wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_timeout(3000)
    except Exception as e:
        print("ERR:", e)
        b.close()
        sys.exit(1)
    print("TITLE:", pg.title())
    print("---BODY---")
    print(pg.inner_text("body")[:2500])
    b.close()
