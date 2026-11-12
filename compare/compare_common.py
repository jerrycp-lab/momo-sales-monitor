# -*- coding: utf-8 -*-
"""
三平台對照用的共用工具（PChome / Yahoo）
- 只記錄商品、價格、折扣，不記錄銷售進度
- 每次抓取把「網頁上看得到的所有檔次」都存下來，同一檔同一商品只留一筆（以最新價格為準，並保留第一次看到的價格）
"""
import csv
import os
import json
import urllib.request
from datetime import datetime, timezone, timedelta

TW = timezone(timedelta(hours=8))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

FIELDS = [
    "date", "slot", "slot_end", "product_id", "name", "slogan",
    "price_origin", "price_sale", "price_first", "discount_pct",
    "discount_text", "url", "first_seen", "last_seen",
]


def now_tw():
    return datetime.now(TW)


def fetch(url, timeout=30, retries=2):
    """下載網頁或資料，失敗重試"""
    last_err = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept-Language": "zh-TW,zh;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last_err = e
    raise last_err


def to_int(v):
    try:
        if v is None or v == "":
            return ""
        return int(float(str(v).replace(",", "").replace("$", "").strip()))
    except Exception:
        return ""


def calc_discount(origin, sale):
    o, s = to_int(origin), to_int(sale)
    if o and s and o > 0 and s <= o:
        return round(s / o * 100)
    return ""


def load_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def upsert(platform, new_rows):
    """把這次抓到的商品合併進該平台的累積檔"""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"{platform}_results.csv")
    rows = load_rows(path)
    index = {(r["date"], r["slot"], r["product_id"]): r for r in rows}
    stamp = now_tw().strftime("%Y/%m/%d %H:%M")

    added = updated = 0
    for n in new_rows:
        key = (n["date"], n["slot"], n["product_id"])
        if key in index:
            old = index[key]
            for k in ("slot_end", "name", "slogan", "price_origin",
                      "price_sale", "discount_pct", "discount_text", "url"):
                if n.get(k) not in (None, ""):
                    old[k] = n[k]
            old["last_seen"] = stamp
            updated += 1
        else:
            n["price_first"] = n.get("price_sale", "")
            n["first_seen"] = stamp
            n["last_seen"] = stamp
            rows.append(n)
            index[key] = n
            added += 1

    rows.sort(key=lambda r: (r["date"], r["slot"]))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    os.replace(tmp, path)
    return path, added, updated, len(rows)


def log_failure(platform, reason):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "scrape_failures.csv")
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "platform", "reason"])
        w.writerow([now_tw().strftime("%Y/%m/%d %H:%M"), platform, str(reason)[:300]])


def report(platform, slots, path, added, updated, total):
    print(f"[{platform}] {now_tw():%Y/%m/%d %H:%M} 抓取完成")
    for s, n in slots:
        print(f"  檔次 {s}：{n} 個商品")
    print(f"  新增 {added} 筆、更新 {updated} 筆，累積 {total} 筆 → {path}")
