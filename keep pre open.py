#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""keep_pre_open.py - 一次性：把「開檔後驟降、已改用開檔後數字」的舊資料，改回用開賣前預抓的數字

背景：momo_scraper v11（2026/11/03～11/24）遇到開檔後 3 分鐘數量比預抓少一半以上，
會改用開檔後的數字，預抓數字存在 qty_pre。但驟降也可能是開賣即被秒殺，
決定（2026/11/24）：保留開賣前數字計算售出，開檔後數字另存 qty_post，前端顯示「📉 驟降」提醒。

本腳本處理 all_results.csv 中 qty_pre > qty_open 的列：
  qty_post = 原 qty_open；qty_open = qty_pre；qty_pre 清空
  sold = max(開檔 - 結束前, 0)；sell_rate 重算；sold_out 不變（依結束前是否為 0）
可重複執行（處理過的列 qty_pre 已清空，不會再動）。
用法：python3 keep_pre_open.py --dry-run   # 預覽
      python3 keep_pre_open.py             # 備份後寫檔
"""
import csv, os, sys, shutil
from datetime import datetime

ALL = os.path.join("snapshots", "all_results.csv")
dry = "--dry-run" in sys.argv

def to_int(v):
    try: return int(str(v).replace(",", "").strip())
    except (ValueError, TypeError): return None

with open(ALL, encoding="utf-8-sig", newline="") as f:
    rd = csv.DictReader(f)
    fields = list(rd.fieldnames)
    rows = list(rd)
if "qty_post" not in fields:
    fields.append("qty_post")

changed, rev_old, rev_new = 0, 0.0, 0.0
for r in rows:
    r.setdefault("qty_post", "")
    pre, o, c = to_int(r.get("qty_pre")), to_int(r.get("qty_open")), to_int(r.get("qty_close"))
    if pre is None or o is None or pre <= o or r.get("data_flag") in ("calc", "doubt"):
        continue
    price = float(str(r.get("price") or 0).replace(",", "") or 0)
    old_sold = to_int(r.get("sold")) or 0
    new_sold = max(pre - (c or 0), 0)
    rev_old += old_sold * price
    rev_new += new_sold * price
    print(f"{r['date']} {r['slot']} {r['icode']:>9} {r['name'][:16]:<16} 開檔 {o:>5} → {pre:>5}  售出 {old_sold:>5} → {new_sold:>5}")
    r["qty_post"] = o
    r["qty_open"] = pre
    r["qty_pre"] = ""
    r["sold"] = new_sold
    r["sell_rate"] = round(new_sold / pre * 100, 1) if pre else 0.0
    changed += 1

print(f"\n共 {changed} 列；這些列的營收合計 ${rev_old:,.0f} → ${rev_new:,.0f}")
if dry or not changed:
    print("（預覽，未寫檔）" if dry else "沒有需要修改的列")
    sys.exit(0)

backup = os.path.join("snapshots", f"all_results_backup_before_keep_pre_{datetime.now():%Y%m%d}.csv")
shutil.copy(ALL, backup)
with open(ALL, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, restval="")
    w.writeheader()
    w.writerows(rows)
print(f"✅ 已寫入 {ALL}，備份：{backup}")
