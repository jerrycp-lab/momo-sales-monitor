# -*- coding: utf-8 -*-
"""
一次性歷史資料修正：舊版抓取程式（2026/10/07 11:00 檔以前）把「倒數：1,951組」只讀成 1，
本腳本把可推估的開檔數量還原成「千位整數」寫回 snapshots/all_results.csv，並用兩個新欄位保留痕跡：
  data_flag  ：calc = 開檔（必要時含中段）已推估還原；doubt = 數量存疑、無法推估，數量與售出以 0 計
  raw_values ：原始數值，格式 開檔|中段|結束前|售出|售出率（供前端顯示「原始紀錄為…」）
規則（與分析頁原本的前端推估完全一致）：
  calc ：同一檔內數量不減反增（例如 開檔1 → 中段949），可確定開檔是千位數，
         以千位整數作為開檔推估值（1 → 1,000），重算售出與售出率（保守估計）
  doubt：同商品在別檔已確定是千位數，這一檔開檔也是個位數但無法從數字判斷，
         品項保留，開檔／中段／結束前／售出一律以 0 計，不計入平均售出率
可重複執行（已處理過的列不會再處理）。執行前自動備份。
執行：
  python3 repair_history.py --dry-run   # 只看統計，不寫檔
  python3 repair_history.py             # 備份後寫回
"""
import csv, os, re, shutil, sys
from datetime import datetime

ALL = os.path.join("snapshots", "all_results.csv")
OLD_LAST = ("2026/10/07", "11:00")        # 此檔（含）以前為舊版抓取程式
NEW_COLS = ["data_flag", "raw_values"]


def is_old(r):
    return r["date"] < OLD_LAST[0] or (r["date"] == OLD_LAST[0] and r["slot"] <= OLD_LAST[1])


def num(v):
    return int(v) if v is not None and re.fullmatch(r"\d+", v) else None


def raw_of(r):
    return "|".join([r["qty_open"], r["mid_qty"], r["qty_close"], r["sold"], r["sell_rate"]])


def main(dry):
    with open(ALL, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = list(reader)
    for c in NEW_COLS:
        if c not in fields:
            fields.append(c)
    for r in rows:
        for c in NEW_COLS:
            r.setdefault(c, "")

    proven, calc, doubt = set(), 0, 0
    for r in rows:                                   # 第一輪：可確定的 calc
        if r["data_flag"] or not is_old(r):
            if r["data_flag"] == "calc":
                proven.add(r["icode"])
            continue
        o, m, c = num(r["qty_open"]), num(r["mid_qty"]), num(r["qty_close"])
        if o is None or o < 1 or o > 9:
            continue
        later = max(m or 0, c or 0)
        if later < 500 or later <= o or later > o * 1000 + 999:
            continue
        est = max(o * 1000, later)
        r["raw_values"] = raw_of(r)
        r["data_flag"] = "calc"
        r["qty_open"] = str(est)
        if m is not None and 1 <= m <= 9 and c is not None and c > m and c >= 500:
            r["mid_qty"] = str(min(max(m * 1000, c), est))
        sold = max(est - (c or 0), 0)
        r["sold"] = str(sold)
        r["sell_rate"] = "%.1f" % (sold / est * 100)
        proven.add(r["icode"])
        calc += 1
    for r in rows:                                   # 第二輪：同商品已證實是千位數，但這列無法推估 → doubt
        if r["data_flag"] or not is_old(r) or r["icode"] not in proven:
            continue
        o = num(r["qty_open"])
        if o is not None and 1 <= o <= 9:
            r["raw_values"] = raw_of(r)
            r["data_flag"] = "doubt"
            r["qty_open"] = r["mid_qty"] = r["qty_close"] = r["sold"] = "0"
            r["sell_rate"] = "0.0"
            doubt += 1

    print(f"共 {len(rows)} 筆：新增推估(calc) {calc} 筆、存疑(doubt) {doubt} 筆")
    if dry:
        print("（--dry-run，未寫檔）")
        return
    if calc == 0 and doubt == 0 and all(c in (reader.fieldnames or []) for c in NEW_COLS):
        print("沒有需要修正的資料，未改動檔案")
        return
    backup = os.path.join("snapshots", f"all_results_backup_before_repair_{datetime.now():%Y%m%d}.csv")
    if not os.path.exists(backup):
        shutil.copy(ALL, backup)
        print(f"已備份 → {backup}")
    with open(ALL, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(rows)
    print(f"✅ 已寫回 {ALL}")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
