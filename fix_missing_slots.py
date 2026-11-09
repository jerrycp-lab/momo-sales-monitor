#!/usr/bin/env python3
"""fix_missing_slots.py - 一次性：移除「整檔抓取失敗」被誤算成全數售完的檔期
條件：同一日期+時段共 >=5 列，且每一列的中段都空白、結尾都是 0、售出 = 開檔
用法: python3 fix_missing_slots.py --dry-run   (只列出，不修改)
      python3 fix_missing_slots.py             (備份後移除)
"""
import csv, os, sys, shutil
from collections import defaultdict
from datetime import datetime

PATH = os.path.join("snapshots", "all_results.csv")
dry = "--dry-run" in sys.argv

with open(PATH, encoding="utf-8-sig", newline="") as f:
    rd = csv.DictReader(f)
    fields = rd.fieldnames
    rows = list(rd)

groups = defaultdict(list)
for i, r in enumerate(rows):
    groups[(r["date"], r["slot"])].append(i)

def bad(r):
    return (r.get("mid_qty", "").strip() == "" and r.get("qty_close", "").strip() in ("0", "0.0")
            and r.get("sold", "").strip() == r.get("qty_open", "").strip())

drop = set()
for key, idx in groups.items():
    if len(idx) >= 5 and all(bad(rows[i]) for i in idx):
        print(f"整檔失敗檔期：{key[0]} {key[1]}（{len(idx)} 列）")
        drop.update(idx)

if not drop:
    print("沒有需要移除的檔期"); sys.exit(0)
if dry:
    print(f"（預覽）共 {len(drop)} 列會被移除"); sys.exit(0)

backup = os.path.join("snapshots", f"all_results_backup_before_missing_fix_{datetime.now():%Y%m%d}.csv")
shutil.copy(PATH, backup)
with open(PATH, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, restval="")
    w.writeheader()
    w.writerows(r for i, r in enumerate(rows) if i not in drop)
print(f"已備份 → {backup}；移除 {len(drop)} 列")
