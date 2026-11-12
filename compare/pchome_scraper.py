# -*- coding: utf-8 -*-
"""
PChome 限時瘋搶 抓取程式
資料來源：https://24h.pchome.com.tw/onsale/ 背後的公開資料介面
一次可拿到今天全部檔次 + 明天第一檔，每檔約 50 個商品
"""
import sys
import json
from datetime import datetime
from compare_common import (fetch, to_int, calc_discount, upsert,
                            log_failure, report)

PLATFORM = "pchome"
API = "https://ecapi-cdn.pchome.com.tw/fsapi/cms/onsale"


def fmt_dt(s):
    """'2026-11-12 10:00:00' → ('2026/11/12', '10:00')"""
    d = datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
    return d.strftime("%Y/%m/%d"), d.strftime("%H:%M")


def parse(data):
    rows, slots = [], []
    for block in data.get("data", []):
        date, slot = fmt_dt(block["startTime"])
        end_d, end_t = fmt_dt(block["endTime"])
        products = block.get("products") or []
        slots.append((f"{date} {slot}", len(products)))
        for p in products:
            price = p.get("price") or {}
            origin, sale = to_int(price.get("origin")), to_int(price.get("onsale"))
            disc = price.get("discount")
            rows.append({
                "date": date,
                "slot": slot,
                "slot_end": f"{end_d} {end_t}",
                "product_id": p.get("id", ""),
                "name": (p.get("name") or "").strip(),
                "slogan": (p.get("slogan") or "").strip(),
                "price_origin": origin,
                "price_sale": sale,
                "discount_pct": calc_discount(origin, sale),
                "discount_text": f"{disc}折" if disc else "",
                "url": p.get("url", ""),
            })
    return rows, slots


def main():
    try:
        data = json.loads(fetch(API))
        rows, slots = parse(data)
        if not rows:
            raise ValueError("資料介面沒有回傳任何商品（可能改版）")
    except Exception as e:
        log_failure(PLATFORM, e)
        print(f"[{PLATFORM}] ❌ 抓取失敗：{e}")
        sys.exit(1)
    path, added, updated, total = upsert(PLATFORM, rows)
    report(PLATFORM, slots, path, added, updated, total)


if __name__ == "__main__":
    main()
