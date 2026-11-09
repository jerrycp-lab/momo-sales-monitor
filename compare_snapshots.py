# -*- coding: utf-8 -*-
"""
momo 限時搶購 - 成效計算程式 v5

v5 修正內容：
  - 配合 momo_scraper.py v7 的三檢查點架構（open / mid / close），
    改為尋找同日期同時段的 open + mid + close 三個檔案配對
  - all_results.csv 新增 mid_qty 欄位，記錄時段中點的庫存，
    方便觀察開檔→中段→結束的趨勢，也能看出是否中途加碼
  - 沿用 v4 的防重複寫入機制

執行方式：
  python compare_snapshots.py
      → 自動配對最新時段（需同時存在 open/mid/close 三個檔案）
  python compare_snapshots.py <open.csv> <mid.csv> <close.csv>
      → 手動指定三個檔案
"""

import csv
import os
import sys
import re
from datetime import datetime, timezone, timedelta
from glob import glob

TW_TZ = timezone(timedelta(hours=8))

OUTPUT_DIR  = "snapshots"
ALL_RESULTS = os.path.join(OUTPUT_DIR, "all_results.csv")
FIELDNAMES  = ["date","slot","icode","brand","name","discount","price",
               "qty_open","mid_qty","qty_close","sold","sold_out","sell_rate",
               "open_source","qty_pre","data_flag","raw_values"]

# momo 六個時段
SLOT_LABELS = {
    "0000": "00:00",
    "0700": "07:00",
    "1100": "11:00",
    "1400": "14:00",
    "1800": "18:00",
    "2200": "22:00",
}


def load_snapshot(filepath: str) -> dict:
    data = {}
    with open(filepath, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            data[row["icode"]] = row
    return data


def parse_file_info(filepath: str):
    """從檔名取得日期、時段、checkpoint，例如 momo_20260806_1100_mid.csv → (20260806, 1100, mid)"""
    base = os.path.basename(filepath)
    m    = re.match(r"momo_(\d{8})_(\d{4})_(open|mid|close)\.csv", base)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None, None, None


def find_latest_trio():
    """找最新的同日期同時段 open + mid + close 三檔配對"""
    closes = sorted(glob(os.path.join(OUTPUT_DIR, "*_close.csv")), reverse=True)

    for close_file in closes:
        date_str, slot, _ = parse_file_info(close_file)
        if not date_str:
            continue
        open_file = os.path.join(OUTPUT_DIR, f"momo_{date_str}_{slot}_open.csv")
        mid_file  = os.path.join(OUTPUT_DIR, f"momo_{date_str}_{slot}_mid.csv")
        if os.path.exists(open_file) and os.path.exists(mid_file):
            return open_file, mid_file, close_file

    return None, None, None


def compare(open_file: str, mid_file: str, close_file: str) -> list:
    snap_open  = load_snapshot(open_file)
    snap_mid   = load_snapshot(mid_file)
    snap_close = load_snapshot(close_file)
    results    = []

    for icode, s in snap_open.items():
        qty_start = int(s["qty"]) if s.get("qty") else None

        mid_raw = snap_mid.get(icode, {}).get("qty", "")
        qty_mid = int(mid_raw) if mid_raw and str(mid_raw).strip() else None

        if icode in snap_close:
            qty_raw  = snap_close[icode].get("qty", "")
            qty_end  = int(qty_raw) if qty_raw and qty_raw.strip() else 0
            sold_out = (qty_end == 0)
        else:
            qty_end  = 0
            sold_out = True

        sold = max(qty_start - qty_end, 0) if qty_start is not None else None
        rate = round(sold / qty_start * 100, 1) if (sold is not None and qty_start) else 0.0

        results.append({
            "icode":     icode,
            "brand":     s.get("brand", ""),
            "name":      s.get("name", ""),
            "discount":  s.get("discount", ""),
            "price":     s.get("price", ""),
            "qty_open":  qty_start,
            "mid_qty":   qty_mid,
            "qty_close": qty_end,
            "sold":      sold,
            "sold_out":  "是" if sold_out else "否",
            "sell_rate": rate,
            "open_source": s.get("source", "") or "",
            "qty_pre":   s.get("qty_pre", "") or "",
        })

    results.sort(key=lambda r: -(r["sold"] or 0))
    return results


def already_recorded(date_str: str, slot_str: str) -> bool:
    """檢查這個日期+時段是否已經寫入過 all_results.csv，避免重複"""
    if not os.path.exists(ALL_RESULTS):
        return False
    with open(ALL_RESULTS, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("date") == date_str and row.get("slot") == slot_str:
                return True
    return False


def migrate_header():
    """all_results.csv 的表頭若缺新欄位，補在最後並把舊資料的新欄位留空；既有欄位（含腳本沒認得的）一律保留"""
    if not os.path.exists(ALL_RESULTS):
        return
    with open(ALL_RESULTS, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        existing = list(reader.fieldnames or [])
        missing = [c for c in FIELDNAMES if c not in existing]
        if not missing:
            return
        rows = list(reader)
    with open(ALL_RESULTS, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=existing + missing, restval="")
        w.writeheader()
        w.writerows(rows)
    print(f"🔧 已補上 {ALL_RESULTS} 缺少的欄位 {missing}（共 {len(rows)} 筆舊資料）")


def current_header() -> list:
    with open(ALL_RESULTS, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f).fieldnames or FIELDNAMES)


def append_to_all_results(results: list, date_str: str, slot_str: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    migrate_header()

    # 防止重複寫入
    if already_recorded(date_str, slot_str):
        print(f"⚠️ {date_str} {slot_str} 已記錄過，跳過寫入")
        return

    file_exists = os.path.exists(ALL_RESULTS)
    fields = current_header() if file_exists else FIELDNAMES   # 依檔案現有表頭順序寫入，不打亂已加工的欄位
    with open(ALL_RESULTS, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", restval="")
        if not file_exists:
            writer.writeheader()
        for r in results:
            writer.writerow({
                "date":      date_str,
                "slot":      slot_str,
                "icode":     r["icode"],
                "brand":     r["brand"],
                "name":      r["name"],
                "discount":  r["discount"],
                "price":     r["price"],
                "qty_open":  r["qty_open"],
                "mid_qty":   r["mid_qty"],
                "qty_close": r["qty_close"],
                "sold":      r["sold"],
                "sold_out":  r["sold_out"],
                "sell_rate": r["sell_rate"],
                "open_source": r.get("open_source", ""),
                "qty_pre":   r.get("qty_pre", ""),
                "data_flag": "",
                "raw_values": "",
            })

    print(f"✅ 已追加 {len(results)} 筆 → {ALL_RESULTS}")


if __name__ == "__main__":
    if len(sys.argv) == 4:
        open_file, mid_file, close_file = sys.argv[1], sys.argv[2], sys.argv[3]
    else:
        open_file, mid_file, close_file = find_latest_trio()
        if not open_file:
            print("❌ 找不到同日期同時段的 open + mid + close 三檔配對")
            sys.exit(1)
        print(f"自動配對：\n  開檔：{open_file}\n  中段：{mid_file}\n  結束前：{close_file}")

    date_str, slot_code, _ = parse_file_info(open_file)
    slot_label = SLOT_LABELS.get(slot_code, slot_code)
    display_date = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}"

    # 結尾快照沒有任何商品 = 當次抓取失敗（被擋、頁面異常等）。此時算出來的「全部售完」是假的，不寫入
    if len(load_snapshot(close_file)) == 0:
        print(f"⚠️ 結尾快照是空的（{os.path.basename(close_file)}），本檔期不計算、不寫入成效資料")
        sys.exit(0)

    results = compare(open_file, mid_file, close_file)
    append_to_all_results(results, display_date, slot_label)

    # 印出摘要
    sold_any = [r for r in results if r["sold"] and r["sold"] > 0]
    sold_out = [r for r in results if r["sold_out"] == "是"]
    print(f"\n{'商品名稱':<22} {'折扣':>5} {'開檔':>6} {'中段':>6} {'結束':>6} {'售出':>6} {'售出率':>7} {'售完':>5}")
    print("─" * 68)
    for r in results:
        print(f"{r['name'][:20]:<22} {r['discount']:>5} "
              f"{str(r['qty_open']):>6} {str(r['mid_qty'] if r['mid_qty'] is not None else '-'):>6} "
              f"{str(r['qty_close']):>6} "
              f"{str(r['sold'] or '-'):>6} {str(r['sell_rate'])+'%':>7} {r['sold_out']:>5}")
    print(f"\n總商品：{len(results)} ｜ 有銷售：{len(sold_any)} ｜ 售完：{len(sold_out)}")
