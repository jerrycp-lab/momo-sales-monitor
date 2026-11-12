# -*- coding: utf-8 -*-
"""
三平台撞品比對（第二階段）
- 品牌：以 momo 的品牌欄位為字典基礎，自動合併「Philips 飛利浦／飛利浦」這類寫法，
        再加上 compare/brand_alias.csv 的人工補充（可排除誤判字）
- 品項：compare/item_keywords.csv 的關鍵字＋商品名稱裡的型號（例如 HY-656、M720）
- 比對：同一天、不同平台
    🔴 同品牌＋同品項（或同型號）→ 值得比價、觀察通路組合差異
    🟡 同品牌、不同品項 → 品牌同日多通路活動
輸出（都在 compare/data/）：
    products_all.csv   三平台商品合併表（含品牌、品項），給通路對照頁使用
    matches.csv        撞品清單
    unknown_brands.csv 找不到品牌的商品，可據此補充 brand_alias.csv
"""
import csv
import os
import re
from collections import defaultdict, Counter

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
DATA = os.path.join(BASE, "data")
MOMO_CSV = os.path.join(ROOT, "snapshots", "all_results.csv")

PLATFORMS = ["momo", "pchome", "yahoo"]
EXCLUDE = "(排除)"

# 型號後面若是這些單位，代表是容量/規格不是型號
UNIT_SUFFIX = re.compile(r"(ML|G|GB|TB|MAH|MM|CM|KG|L|W|LB|HZ|M|P|K|V|A|X|入|包|片|抽)$")


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def is_ascii(s):
    return all(ord(c) < 128 for c in s)


def split_tokens(brand):
    """'Philips 飛利浦' → ['philips', '飛利浦']；英文詞組內的空白保留（NEW BALANCE）"""
    parts = re.findall(r"[A-Za-z0-9][A-Za-z0-9 .&'\-]*[A-Za-z0-9]|[A-Za-z0-9]|[^\x00-\x7F\s]+", brand)
    out = []
    for p in parts:
        p = p.strip()
        if is_ascii(p):
            # 英文至少 2 字且要有字母（排除「100」這類數字）
            if len(p) >= 2 and re.search(r"[A-Za-z]", p):
                out.append(p.lower())
        elif len(p) >= 2:
            out.append(p)
    return out


# ---------------- 品牌字典 ----------------
def clean_brand(raw, kws):
    """momo 品牌欄位有時是整串商品名稱（例如「ANKER A1695行動電源 165W…」），
    這種情況只取開頭的英文品牌；取不到就回傳空字串，改由商品名稱判斷"""
    b = BrandBook.NOISE.sub("", raw or "").strip()
    junk = (len(b) > 24
            or (len(b) > 8 and re.search(r"[0-9（）()\[\]/+×：:、．‧!！]", b))
            or (len(b) > 6 and any(k in b for k in kws)))
    if not junk:
        return b
    m = re.match(r"([A-Za-z][A-Za-z&'.\- ]*[A-Za-z])", b)
    return m.group(1).strip() if m and len(m.group(1).strip()) >= 2 else ""


class BrandBook:
    def __init__(self, momo_rows, alias_rows, item_kws=()):
        self.excluded = set()
        manual = {}
        for r in alias_rows:
            a = (r.get("別名") or "").strip()
            b = (r.get("標準品牌（填「(排除)」代表這個字不要當品牌用）") or
                 list(r.values())[1] or "").strip()
            if not a or not b:
                continue
            key = a.lower() if is_ascii(a) else a
            if b == EXCLUDE:
                self.excluded.add(key)
            else:
                manual[key] = b

        # 以 momo 品牌字串建群組（共用 token 的視為同一品牌）
        kws = {k for k in item_kws if len(k) >= 2}
        self.raw_clean = {}
        for r in momo_rows:
            raw = r.get("brand", "").strip()
            if raw and raw not in self.raw_clean:
                self.raw_clean[raw] = clean_brand(raw, kws)
        counts = Counter()
        for r in momo_rows:
            c = self.raw_clean.get(r.get("brand", "").strip(), "")
            if c:
                counts[c] += 1
        parent = {}

        def find(x):
            while parent.setdefault(x, x) != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # 只在「某個 token 本身就是另一個完整品牌」時合併，
        # 例如「Philips 飛利浦」的「飛利浦」剛好是品牌「飛利浦」→ 合併；避免不相關品牌連鎖併在一起
        full = {}
        for b in counts:
            find("B:" + b)
            full[b.lower() if is_ascii(b) else b] = b
        for b in counts:
            for t in split_tokens(b):
                if t in self.excluded or t in manual:
                    continue
                if t in full and full[t] != b:
                    union("B:" + full[t], "B:" + b)

        groups = defaultdict(list)
        for b in counts:
            groups[find("B:" + b)].append(b)
        # 群組顯示名稱：出現次數最多的寫法
        self.canon_of_momo = {}
        for root, members in groups.items():
            canon = max(members, key=lambda m: counts[m])
            for m in members:
                self.canon_of_momo[m] = canon

        # 別名 → 品牌：同一個字若屬於多個品牌，取商品數最多的那個
        votes = defaultdict(Counter)
        for m, canon in self.canon_of_momo.items():
            keys = {m.lower() if is_ascii(m) else m} | set(split_tokens(m))
            for k in keys:
                if not is_ascii(k) and len(k) > 8:
                    continue  # 太長的中文字串不當別名
                if k not in self.excluded and k not in manual:
                    votes[k][canon] += counts[m]
        alias = {k: c.most_common(1)[0][0] for k, c in votes.items()}

        # 人工別名優先；人工標準名若剛好是 momo 某品牌的寫法，統一成該群組名稱
        for a, b in manual.items():
            alias[a] = self.canon_of_momo.get(b, b)
        # momo 自己的品牌，如果人工表把它的 token 指到別的標準名，也一起改
        for m in list(self.canon_of_momo):
            for t in split_tokens(m):
                if t in manual:
                    self.canon_of_momo[m] = alias[t]
                    break

        self.alias = alias
        ascii_alias = sorted([a for a in alias if is_ascii(a)], key=len, reverse=True)
        cjk_alias = sorted([a for a in alias if not is_ascii(a)], key=len, reverse=True)
        self.re_ascii = re.compile(
            r"(?<![A-Za-z0-9])(" + "|".join(re.escape(a) for a in ascii_alias) + r")(?![A-Za-z0-9])",
            re.I) if ascii_alias else None
        self.re_cjk = re.compile("|".join(re.escape(a) for a in cjk_alias)) if cjk_alias else None

    def momo_brand(self, raw, name=""):
        c = self.raw_clean.get((raw or "").strip(), "")
        if c:
            return self.canon_of_momo.get(c, c)
        return self.detect(name)

    def detect(self, name):
        """從商品名稱找品牌：【】內優先，其次最前面出現的、最長的"""
        hits = []
        for rx in (self.re_ascii, self.re_cjk):
            if not rx:
                continue
            for m in rx.finditer(name):
                key = m.group(0).lower() if is_ascii(m.group(0)) else m.group(0)
                if key in self.alias:
                    hits.append((m.start(), -len(key), self.alias[key]))
        bracket = re.search(r"【([^】]+)】", name)
        if not hits:
            return self.guess(name, bracket)
        if bracket:
            s, e = bracket.span(1)
            inside = [h for h in hits if s <= h[0] < e]
            if inside:
                return min(inside)[2]
        return min(hits)[2]

    NOISE = re.compile(r"(官方旗艦店|官方旗艦|官方直營|旗艦館|旗艦店|直營|官方|雙11限定|限定|爆買|人氣|下殺|週週好給利)")

    def guess(self, name, bracket):
        """字典找不到時的備案：【】內的字，或名稱開頭的英文品牌（YAMADA、KIOXIA…）"""
        if bracket:
            g = self.NOISE.sub("", bracket.group(1))
            g = re.sub(r"^(德國|日本|美國|法國|英國|義大利|瑞士|韓國|台灣)\s*", "", g).strip(" ｜|-")
            if 2 <= len(g) <= 20:
                return g
        s = re.sub(r"^[\(（\[][^\)）\]]*[\)）\]]\s*|^[*★]+", "", name).strip()
        m = re.match(r"([A-Za-z][A-Za-z0-9&'\-]+(?: [A-Z][A-Za-z0-9&'\-]+)?)", s)
        if m and len(m.group(1)) >= 2:
            g = m.group(1)
            key = g.lower()
            if key in self.excluded:
                return ""
            return g.upper() if len(g) <= 4 else g
        return ""


# ---------------- 品項 ----------------
def load_items(path):
    items = []
    for r in read_csv(path):
        vals = list(r.values())
        name = (vals[0] or "").strip()
        kws = [k.strip() for k in (vals[1] or "").split("|") if k.strip()]
        if name and kws:
            items.append((name, kws))
    return items


def tag_items(name, items):
    up = name.upper()
    return [n for n, kws in items if any(k.upper() in up for k in kws)]


# 型號：字母+數字（HY-656、M720、DLP4347C）、數字+字母（7530U），或獨立 5 位數（樂高 42206）
MODEL_RX = re.compile(r"(?<![A-Z0-9])([A-Z]{1,5}-?\d{2,6}[A-Z0-9\-]*|\d{3,5}[A-Z]{1,3}|\d{5})(?![A-Z0-9])")


def models(name):
    out = set()
    for m in MODEL_RX.findall(name.upper()):
        m = m.strip("-")
        if UNIT_SUFFIX.search(m) and not re.search(r"[A-Z]{2,}-?\d", m):
            continue
        if re.fullmatch(r"20\d\d", m):
            continue
        out.add(m.replace("-", ""))
    return out


# ---------------- 資料整理 ----------------
def momo_discount(text):
    m = re.search(r"(\d+)", text or "")
    if not m:
        return ""
    n = int(m.group(1))
    return n * 10 if n < 10 else n


def load_all(book, items):
    pch = read_csv(os.path.join(DATA, "pchome_results.csv"))
    yah = read_csv(os.path.join(DATA, "yahoo_results.csv"))
    start = min([r["date"] for r in pch + yah] or ["9999/99/99"])

    merged = {}  # (platform, date, product_id) → row（同一天多檔合併）

    def put(platform, r, pid, brand, price_origin, price_sale, disc, url):
        key = (platform, r["date"], pid)
        if key in merged:
            slots = merged[key]["slot"].split("/")
            if r["slot"] not in slots:
                merged[key]["slot"] = "/".join(sorted(slots + [r["slot"]]))
            return
        name = r["name"].strip()
        merged[key] = {
            "platform": platform, "date": r["date"], "slot": r["slot"],
            "product_id": pid, "brand": brand,
            "items": "|".join(tag_items(name, items)),
            "models": "|".join(sorted(models(name))),
            "name": name, "price_origin": price_origin, "price_sale": price_sale,
            "discount_pct": disc, "url": url,
        }

    for r in read_csv(MOMO_CSV):
        if r.get("date", "") < start:
            continue
        put("momo", r, r["icode"], book.momo_brand(r.get("brand"), r.get("name", "")),
            "", r.get("price", ""), momo_discount(r.get("discount")),
            f"https://www.momoshop.com.tw/goods/GoodsDetail.jsp?i_code={r['icode']}")
    for platform, rows in (("pchome", pch), ("yahoo", yah)):
        for r in rows:
            put(platform, r, r["product_id"], book.detect(r["name"]),
                r["price_origin"], r["price_sale"], r["discount_pct"], r["url"])

    return sorted(merged.values(), key=lambda x: (x["date"], x["platform"], x["slot"]))


def find_matches(rows):
    by_day_brand = defaultdict(list)
    for r in rows:
        if r["brand"]:
            by_day_brand[(r["date"], r["brand"])].append(r)

    out = []
    for (date, brand), group in sorted(by_day_brand.items()):
        if len({r["platform"] for r in group}) < 2:
            continue
        used = set()
        # 🔴 先比型號，再比品項
        for kind, field in (("型號", "models"), ("品項", "items")):
            bucket = defaultdict(list)
            for r in group:
                for v in filter(None, r[field].split("|")):
                    bucket[v].append(r)
            for v, members in sorted(bucket.items(), key=lambda kv: -len(kv[1])):
                members = [m for m in members if id(m) not in used]
                if len({m["platform"] for m in members}) < 2:
                    continue
                for m in members:
                    used.add(id(m))
                    out.append({**m, "level": "同品項", "match_key": f"{kind}:{v}"})
        # 🟡 其餘
        rest = [r for r in group if id(r) not in used]
        if len({r["platform"] for r in group}) >= 2 and rest:
            for r in rest:
                out.append({**r, "level": "同品牌", "match_key": ""})

    order = {"同品項": 0, "同品牌": 1}
    out.sort(key=lambda r: (r["date"], order[r["level"]], r["brand"], r["match_key"],
                            PLATFORMS.index(r["platform"])))
    return out


def main():
    momo_rows = read_csv(MOMO_CSV)
    items = load_items(os.path.join(BASE, "item_keywords.csv"))
    book = BrandBook(momo_rows, read_csv(os.path.join(BASE, "brand_alias.csv")),
                     [k for _, kws in items for k in kws])

    rows = load_all(book, items)
    matches = find_matches(rows)

    os.makedirs(DATA, exist_ok=True)
    pfields = ["platform", "date", "slot", "product_id", "brand", "items", "models",
               "name", "price_origin", "price_sale", "discount_pct", "url"]
    write_csv(os.path.join(DATA, "products_all.csv"), pfields, rows)
    write_csv(os.path.join(DATA, "matches.csv"), ["date", "level", "brand", "match_key"] + pfields[:1] + pfields[2:4] + pfields[5:], matches)

    unknown = Counter()
    for r in rows:
        if r["platform"] != "momo" and not r["brand"]:
            unknown[(r["platform"], r["name"])] += 1
    write_csv(os.path.join(DATA, "unknown_brands.csv"), ["platform", "name", "count"],
              [{"platform": p, "name": n, "count": c} for (p, n), c in unknown.most_common()])

    # 摘要
    total = Counter(r["platform"] for r in rows)
    branded = Counter(r["platform"] for r in rows if r["brand"])
    print(f"[比對] 起始日 {rows[0]['date'] if rows else '-'}，商品數：" +
          "、".join(f"{p} {total[p]}（有品牌 {branded[p]}）" for p in PLATFORMS))
    red = {(m["date"], m["brand"], m["match_key"]) for m in matches if m["level"] == "同品項"}
    yel = {(m["date"], m["brand"]) for m in matches if m["level"] == "同品牌"}
    print(f"[比對] 🔴 同品牌同品項 {len(red)} 組、🟡 同品牌 {len(yel)} 組；找不到品牌 {sum(1 for r in rows if r['platform'] != 'momo' and not r['brand'])} 個")


if __name__ == "__main__":
    main()
