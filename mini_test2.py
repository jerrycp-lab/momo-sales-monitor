import sys
from playwright.sync_api import sync_playwright

icode = sys.argv[1]
url = f"https://www.momoshop.com.tw/goods/GoodsDetail.jsp?i_code={icode}"

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.goto(url, wait_until="domcontentloaded", timeout=30000)
    pg.wait_for_timeout(3000)

    result = pg.evaluate("""
    () => {
        const cats = ['家電','電玩','手機/相機','電腦/組件','3C週邊','保健/醫療','食品/飲料','生鮮','女時尚','男時尚','精品/飾品','彩妝保養','個人清潔','日用/紙品','母嬰/玩具','餐廚','家具收納','修繕園藝','傢飾寢具','寵物','運動/按摩','戶外','車類','圖書影音','文具樂器','藝術宗教','旅遊/住宿','票券','加值/軟體','綠色生活','生活超市','跨境好物'];
        const out = [];
        document.querySelectorAll('a,li,span').forEach(el => {
            const t = (el.textContent||'').trim();
            if (cats.includes(t) && el.children.length===0) {
                out.push(t+'|'+el.tagName+'|cls='+el.className+'|parentCls='+(el.parentElement?el.parentElement.className:''));
            }
        });
        return out;
    }
    """)
    for r in result:
        print(r)
    b.close()
