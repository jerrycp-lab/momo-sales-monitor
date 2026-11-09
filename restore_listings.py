#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""restore_listings.py - 一次性：把「抓取中斷」檔期留下的商品明細，整理成只供查詢的 listing_only.csv

背景：2026/11/07 23:55 起 momo 擋掉舊版瀏覽器，到 11/09 14:03 才恢復。
這段期間有 3 個檔期留下部分快照，商品、價格、數量是對的，但沒有完整的開檔→結尾，算不出售出量：
  2026/11/07 22:00：有開檔（提前抓）＋中段，結尾抓取失敗
                    → 原本被誤算成 65 件全數售完，本腳本會從 all_results.csv 移除
  2026/11/08 00:00：只有 11/07 22:03 提前抓的開檔數字
  2026/11/09 11:00：只有 13:55 結尾前的數字（恢復當天第一次抓到）

輸出 snapshots/listing_only.csv：儀表板可查詢這些商品，但不計入任何銷售統計；
交叉分析頁不讀這個檔案，所以統計完全不受影響。

可重複執行（每次重新產生 listing_only.csv；all_results.csv 已移除過就不會再動）。
用法：python3 restore_listings.py --dry-run   # 只看結果，不寫檔
      python3 restore_listings.py             # 備份後寫檔
"""
import csv, os, sys, shutil
from datetime import datetime

SNAP = "snapshots"
ALL = os.path.join(SNAP, "all_results.csv")
OUT = os.path.join(SNAP, "listing_only.csv")
TARGETS = [("2026/11/07", "22:00"), ("2026/11/08", "00:00"), ("2026/11/09", "11:00")]
OUT_FIELDS = ["date", "slot", "icode", "brand", "name", "discount", "old_price", "price",
              "qty_open", "mid_qty", "qty_close", "open_source", "note"]
dry = "--dry-run" in sys.argv


def read_snap(date, slot, cp):
    p = os.path.join(SNAP, f"momo_{date.replace('/', '')}_{slot.replace(':', '')}_{cp}.csv")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8-sig", newline="") as f:
        return {r["icode"]: r for r in csv.DictReader(f) if r.get("icode")}


out_rows = []
for date, slot in TARGETS:
    snaps = {cp: read_snap(date, slot, cp) for cp in ("open", "mid", "close")}
    have = [cp for cp in ("open", "mid", "close") if snaps[cp]]
    note = {"open": "開檔前", "mid": "中段", "close": "結束前"}
    note_txt = "抓取中斷，僅有" + "、".join(note[c] for c in have) + "數量"
    order = []
    for cp in ("open", "mid", "close"):
        for ic in snaps[cp]:
            if ic not in order:
                order.append(ic)
    for ic in order:
        base = snaps["open"].get(ic) or snaps["mid"].get(ic) or snaps["close"].get(ic)
        out_rows.append({
            "date": date, "slot": slot, "icode": ic,
            "brand": base.get("brand", ""), "name": base.get("name", ""),
            "discount": base.get("discount", ""), "old_price": base.get("old_price", ""),
            "price": base.get("price", ""),
            "qty_open": snaps["open"].get(ic, {}).get("qty", ""),
            "mid_qty": snaps["mid"].get(ic, {}).get("qty", ""),
            "qty_close": snaps["close"].get(ic, {}).get("qty", ""),
            "open_source": snaps["open"].get(ic, {}).get("source", ""),
            "note": note_txt,
        })
    print(f"{date} {slot}：{len(order)} 件（{note_txt}）")

# all_results.csv：移除 TARGETS 中結尾快照是空的檔期（會被誤算成全數售完）
with open(ALL, encoding="utf-8-sig", newline="") as f:
    rd = csv.DictReader(f)
    fields = rd.fieldnames
    rows = list(rd)
drop_keys = {(d, s) for d, s in TARGETS if not read_snap(d, s, "close")}
keep = [r for r in rows if (r["date"], r["slot"]) not in drop_keys]
removed = len(rows) - len(keep)
for d, s in sorted(drop_keys):
    n = sum(1 for r in rows if (r["date"], r["slot"]) == (d, s))
    if n:
        print(f"all_results.csv 將移除 {d} {s}：{n} 列（結尾抓取失敗、被誤算成售完）")

if dry:
    print(f"（預覽）listing_only.csv 共 {len(out_rows)} 列；all_results.csv 移除 {removed} 列。未寫檔。")
    sys.exit(0)

with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
    w.writeheader()
    w.writerows(out_rows)
print(f"✅ 已寫入 {OUT}（{len(out_rows)} 列）")

if removed:
    backup = os.path.join(SNAP, f"all_results_backup_before_listing_fix_{datetime.now():%Y%m%d}.csv")
    shutil.copy(ALL, backup)
    with open(ALL, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(keep)
    print(f"✅ all_results.csv 已移除 {removed} 列，備份：{backup}")
else:
    print("all_results.csv 不需要修改")
