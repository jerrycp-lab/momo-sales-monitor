#!/usr/bin/env python3
"""check_anomalies.py v1 - 數據異常告警
讀 snapshots/all_results.csv，把可疑的列寫進 snapshots/data_alerts.csv
用法: python3 check_anomalies.py            # 只掃最近 3 天（run_monitor.sh 用）
      python3 check_anomalies.py --all      # 掃全部歷史
      python3 check_anomalies.py --days 7
重複執行安全：被掃描日期的告警會整批重寫，其他日期保留。
"""
import csv, os, sys, statistics
from collections import defaultdict
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "snapshots", "all_results.csv")
OUT = os.path.join(BASE, "snapshots", "data_alerts.csv")
FIELDS = ["date", "slot", "type", "severity", "icode", "name", "detail"]

SHARE_LIMIT = 0.25        # 單列營收占當日 > 25%
SHARE_MIN_REV = 3_000_000 # 且 > 300 萬才告警
MID_BLANK_RATIO = 0.3     # 整檔中段空白比例 > 30% 視為中段漏抓
RESTOCK_RATIO = 1.10      # 結尾 > 中段 10% 以上
RESTOCK_MIN = 20          # 且差額 >= 20
COUNT_RATIO = 0.5         # 檔期商品數 < 近期同時段中位數 50%
OLD_PARSER_LAST = ("2026/10/07", "11:00")

def num(v):
    try: return float(str(v).replace(",", "")) if str(v).strip() != "" else None
    except ValueError: return None

def main():
    args = sys.argv[1:]
    days = 3
    scan_all = "--all" in args
    if "--days" in args: days = int(args[args.index("--days") + 1])
    with open(SRC, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows: return
    dates = sorted({r["date"] for r in rows})
    if scan_all: scan = set(dates)
    else:
        last = datetime.strptime(dates[-1], "%Y/%m/%d")
        scan = {d for d in dates if datetime.strptime(d, "%Y/%m/%d") >= last - timedelta(days=days - 1)}

    slots = sorted({(r["date"], r["slot"]) for r in rows})
    prev_slot = {s: slots[i - 1] for i, s in enumerate(slots) if i}
    close_of = {(r["date"], r["slot"], r["icode"]): num(r["qty_close"]) for r in rows}
    day_rev = defaultdict(float); slot_cnt = defaultdict(int)
    for r in rows:
        o, p, s = num(r["qty_open"]), num(r["price"]), num(r["sold"])
        day_rev[r["date"]] += (s or 0) * (p or 0)
        slot_cnt[(r["date"], r["slot"])] += 1

    last_close = {}          # icode -> (date, slot, 結尾庫存)，依時間順序往後更新
    prev_close_at = {}       # (date, slot, icode) -> 該品號「更早一檔」的結尾庫存
    for r in sorted(rows, key=lambda x: (x["date"], x["slot"])):
        k = (r["date"], r["slot"], r["icode"])
        if r["icode"] in last_close: prev_close_at[k] = last_close[r["icode"]]
        c = num(r["qty_close"])
        if c is not None: last_close[r["icode"]] = c

    alerts = []
    def add(r, typ, sev, detail):
        alerts.append({"date": r["date"], "slot": r["slot"], "type": typ, "severity": sev,
                       "icode": r["icode"], "name": r["name"][:40], "detail": detail})

    for r in rows:
        if r["date"] not in scan: continue
        o, m, c = num(r["qty_open"]), num(r["mid_qty"]), num(r["qty_close"])
        s, p = num(r["sold"]), num(r["price"]) or 0
        old = (r["date"], r["slot"]) <= OLD_PARSER_LAST
        flag = r.get("data_flag", "")
        if flag in ("calc", "doubt"): continue   # 已知舊版漏位數，不重複告警
        rev = (s or 0) * p
        if day_rev[r["date"]] and rev >= SHARE_MIN_REV and rev / day_rev[r["date"]] > SHARE_LIMIT:
            pc0 = prev_close_at.get((r["date"], r["slot"], r["icode"]))
            consistent = pc0 and o and abs(o - pc0) <= max(0.05 * pc0, 10)
            share = f"營收 ${rev:.0f} 占當日 {rev / day_rev[r['date']]:.0%}"
            if consistent:   # 開檔與該品上次結尾相符 → 庫存是真的，只是金額大，降為提醒
                add(r, "單列營收過大", "低", share + f"（開檔 {o:.0f} 與上次結尾 {pc0:.0f} 相符，應屬真實）")
            else:
                add(r, "單列營收過大", "高", share)
        ps = prev_slot.get((r["date"], r["slot"]))
        if ps and o and m is not None and o >= 200 and m <= 0.2 * o:
            pc = close_of.get((ps[0], ps[1], r["icode"]))
            if pc is not None and pc == o:
                add(r, "開檔疑似沿用上檔庫存", "高", f"開檔 {o:.0f} = 上一檔結尾，中段僅 {m:.0f}")
        if o is not None and s is not None and s > o:
            add(r, "售出大於開檔", "高", f"開檔 {o:.0f}，售出 {s:.0f}")
        if m is not None and c is not None and not (old and m <= 9) and m > 0 \
           and c > m * RESTOCK_RATIO and c - m >= RESTOCK_MIN:
            add(r, "結尾庫存高於中段(加量)", "低", f"中段 {m:.0f} → 結尾 {c:.0f}")

    # 中段整檔漏抓（個別售完品中段空白屬正常，所以只看整檔比例）
    blank = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["date"] not in scan or (r["date"], r["slot"]) <= OLD_PARSER_LAST: continue
        c = num(r["qty_close"])
        if c and c > 0:
            blank[(r["date"], r["slot"])][1] += 1
            if r["mid_qty"].strip() == "": blank[(r["date"], r["slot"])][0] += 1
    for (d, sl), (b, n) in blank.items():
        if n >= 5 and b / n > MID_BLANK_RATIO:
            alerts.append({"date": d, "slot": sl, "type": "中段數量整檔漏抓", "severity": "中", "icode": "",
                           "name": "", "detail": f"{b}/{n} 件中段空白，售出量以結尾推算可能偏低"})

    # 檔期商品數驟降
    by_slot = defaultdict(list)
    for (d, sl), n in slot_cnt.items(): by_slot[sl].append((d, n))
    for sl, lst in by_slot.items():
        lst.sort()
        for i, (d, n) in enumerate(lst):
            if d not in scan or i < 5: continue
            med = statistics.median(x[1] for x in lst[max(0, i - 14):i])
            if med >= 10 and n < med * COUNT_RATIO:
                alerts.append({"date": d, "slot": sl, "type": "檔期商品數驟降", "severity": "中",
                               "icode": "", "name": "", "detail": f"本檔 {n} 件，近期同時段中位數 {med:.0f} 件（可能漏抓）"})

    old_rows = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8-sig", newline="") as f:
            old_rows = [x for x in csv.DictReader(f) if x["date"] not in scan]
    allrows = old_rows + alerts
    allrows.sort(key=lambda x: (x["date"], x["slot"]))
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(allrows)
    cnt = defaultdict(int)
    for a in alerts: cnt[(a["type"], a["severity"])] += 1
    print(f"✅ 告警檢查完成：掃描 {len(scan)} 天，{len(alerts)} 則")
    for (t, sv), n in sorted(cnt.items(), key=lambda x: -x[1]): print(f"   [{sv}] {t}: {n}")

if __name__ == "__main__":
    main()
