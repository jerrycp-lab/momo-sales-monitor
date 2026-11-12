# -*- coding: utf-8 -*-
"""
Yahoo 購物中心 秒殺時時樂 抓取程式
資料來源：https://tw.buy.yahoo.com/rushbuy 網頁內嵌的商品資料（不用開瀏覽器）
一次可拿到今天全部檔次（08:00 / 15:00 / 21:00），每檔約 30 個商品
注意：網頁畫面上未開賣的價格會顯示 $1,XXX，但內嵌資料是完整價格
"""
import sys
import re
import json
from datetime import datetime
from compare_common import (TW, fetch, to_int, calc_discount, upsert,
                            log_failure, report)

PLATFORM = "yahoo"
URL = "https://tw.buy.yahoo.com/rushbuy"


def field(obj, name):
    """Yahoo 的欄位名稱可能帶參數，例如 title({"revertYIV":true})"""
    for k, v in obj.items():
        if k == name or k.startswith(name + "("):
            return v
    return ""


def fmt_ts(ts):
    d = datetime.fromisoformat(ts).astimezone(TW)
    return d.strftime("%Y/%m/%d"), d.strftime("%H:%M")


def extract_state(html):
    for m in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.S):
        s = m.group(1)
        if "Sas_Rushbuy_Product" in s:
            return json.loads(s[s.find("{"): s.rfind("}") + 1])
    return None


def parse(state):
    acts = {k: v for k, v in state.items() if k.startswith("Sas_Rushbuy_Activity:")}
    prods = {k: v for k, v in state.items() if k.startswith("Sas_Rushbuy_Product:")}

    # 每個檔次各自展開它的商品（同一商品出現在多檔時，每檔各記一筆）
    pairs, seen = [], set()
    for ak, a in acts.items():
        for pk in re.findall(r'"__ref":\s*"(Sas_Rushbuy_Product:\d+)"', json.dumps(a)):
            if pk in prods and (ak, pk) not in seen:
                seen.add((ak, pk))
                pairs.append((a, prods[pk]))
    matched = {pk for _, pk in seen}

    rows, slot_count = [], {}
    for a, p in pairs:
        date, slot = fmt_ts(a["startTs"])
        end_d, end_t = fmt_ts(a["endTs"])
        origin, sale = to_int(p.get("price")), to_int(p.get("promotionPrice"))
        pid = p.get("propertyProductId") or p.get("id", "")
        rows.append({
            "date": date,
            "slot": slot,
            "slot_end": f"{end_d} {end_t}",
            "product_id": str(pid),
            "name": (field(p, "title") or field(p, "promotionTitle") or "").strip(),
            "slogan": (field(p, "subtitle") or "").strip(),
            "price_origin": origin,
            "price_sale": sale,
            "discount_pct": calc_discount(origin, sale),
            "discount_text": (p.get("discount") or "").replace(" ", ""),
            "url": p.get("itemUrl", ""),
        })
        key = f"{date} {slot}"
        slot_count[key] = slot_count.get(key, 0) + 1

    return rows, sorted(slot_count.items()), len(prods), len(matched)


def main():
    try:
        html = fetch(URL)
        state = extract_state(html)
        if not state:
            raise ValueError("網頁裡找不到商品資料（可能被擋或改版）")
        rows, slots, raw_n, matched_n = parse(state)
        if not rows:
            raise ValueError(f"找到 {raw_n} 個商品但都對不到檔次")
    except Exception as e:
        log_failure(PLATFORM, e)
        print(f"[{PLATFORM}] ❌ 抓取失敗：{e}")
        sys.exit(1)
    path, added, updated, total = upsert(PLATFORM, rows)
    report(PLATFORM, slots, path, added, updated, total)
    if matched_n < raw_n:
        print(f"  ⚠️ 有 {raw_n - matched_n} 個商品對不到檔次，已略過")


if __name__ == "__main__":
    main()
