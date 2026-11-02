# -*- coding: utf-8 -*-
"""
一次性補欄位：把原始快照 snapshots/momo_*_open.csv 的 source（pre=提前抓 / open=開檔後抓）
回填到 snapshots/all_results.csv 新增的 open_source 欄位，讓前端可以辨識「開檔數字是提前抓的」。
- 只填 open_source 還是空白的列；可重複執行
- 舊快照（v10 以前）沒有 source 欄，維持空白（代表開檔後抓）
執行：python3 backfill_open_source.py
"""
import csv, os, re
from glob import glob

OUT = "snapshots"
ALL = os.path.join(OUT, "all_results.csv")
FIELDS = ["date","slot","icode","brand","name","discount","price","qty_open","mid_qty","qty_close",
          "sold","sold_out","sell_rate","open_source","qty_pre"]

src = {}
for fp in glob(os.path.join(OUT, "momo_*_open.csv")):
    m = re.match(r"momo_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})_open\.csv", os.path.basename(fp))
    if not m:
        continue
    date = f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    slot = f"{m.group(4)}:{m.group(5)}"
    with open(fp, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("icode") and r.get("source"):
                src[(date, slot, r["icode"])] = r["source"]

with open(ALL, encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

filled = pre = 0
for r in rows:
    if not r.get("open_source"):
        s = src.get((r["date"], r["slot"], r["icode"]), "")
        if s:
            r["open_source"] = s
            filled += 1
            pre += (s == "pre")

with open(ALL, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore", restval="")
    w.writeheader()
    w.writerows(rows)

print(f"✅ 共 {len(rows)} 筆，回填 open_source {filled} 筆（其中提前抓 pre：{pre} 筆）")
