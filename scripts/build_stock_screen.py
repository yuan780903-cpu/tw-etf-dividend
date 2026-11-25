"""個股估價篩選器資料 -> data/stk_screen.json
讀 data/stk/<代號>.json(build_stock_pages.py 產生:便宜/合理/昂貴價＝股利法、本益比法、淨值比法三法平均)、
   data/stock_div.json(每年現金股利)、data/fund/fundamentals.json(每年年底股價 pxY,沒有就略過平均殖利率)、
   data/holdings/0050.json、0051.json(官方成分股:台灣50、中型100)
欄位見 cols。景氣循環股:依產業＋面板、記憶體(DRAM)個股,名單在 CYC_IND / CYC_CODE。
"""
import json, os, glob, datetime as dt

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CYC_IND = ["航運業", "鋼鐵工業", "塑膠工業", "化學工業", "水泥工業", "造紙工業", "玻璃陶瓷", "橡膠工業", "油電燃氣業", "建材營造"]
CYC_CODE = {"2409": "面板", "3481": "面板", "6116": "面板", "8105": "面板",
            "2408": "記憶體", "2344": "記憶體", "2337": "記憶體", "6770": "記憶體", "3260": "記憶體", "4967": "記憶體", "8299": "記憶體"}


def load(p, default=None):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return default


def R(x, n=2): return None if x is None else round(x, n)


def main():
    stk = {}
    for p in glob.glob(os.path.join(DATA, "stk", "*.json")):
        d = load(p)
        if d and d.get("c"): stk[d["c"]] = d
    name2c = {}
    for c, d in stk.items(): name2c.setdefault(d.get("n"), c)

    def members(etf):
        h = load(os.path.join(DATA, "holdings", etf + ".json"), {}) or {}
        rows = h.get("full") or [[x[1], None, x[2]] for x in (h.get("top10") or [])]
        got = [name2c.get(r[0]) for r in rows if r and r[0]]
        return {c for c in got if c}, len(rows), h.get("fullDate") or h.get("top10Date")
    t50, n50, d50 = members("0050")
    m100, n100, d100 = members("0051")
    # 對不到名稱時,用上市市值排名補(台灣50=前 50、中型100=51~150)
    rank = [c for c, d in sorted(stk.items(), key=lambda kv: -(kv[1].get("mcap") or 0)) if d.get("mkt") == "上市"]
    if len(t50) < 45: t50 = set(rank[:50])
    if len(m100) < 90: m100 = set(rank[50:150]) - t50

    SD = (load(os.path.join(DATA, "stock_div.json"), {}) or {}).get("stocks", {})
    F = (load(os.path.join(DATA, "fund", "fundamentals.json"), {}) or {}).get("companies", {})
    this_year = dt.date.today().year

    rows = []
    for c, d in stk.items():
        v = d.get("val") or {}
        avg = v.get("avg") if v.get("avg") and len(v["avg"]) == 3 and all(v["avg"]) else None
        px = d.get("px")
        m = d.get("m") or {}
        # 近幾年平均殖利率:每年現金股利 ÷ 當年年底股價(只算已經過完的年度)
        ys = []
        pxY = (F.get(c) or {}).get("pxY") or {}
        for y, x in ((SD.get(c) or {}).get("y") or {}).items():
            if int(y) >= this_year: continue
            p = pxY.get(str(y))
            if p and p > 0 and x.get("cash") is not None: ys.append(x["cash"] / p * 100)
        ya = R(sum(ys) / len(ys), 2) if len(ys) >= 3 else None
        ind = d.get("ind") or ""
        cyc = CYC_CODE.get(c) or ("產業" if ind in CYC_IND else "")
        grp = 1 if c in t50 else 2 if c in m100 else 0
        rows.append([c, d.get("n"), ind, d.get("mkt"), px, R(d.get("chg")),
                     *(R(x) for x in (avg or [None, None, None])), (v.get("zone") if avg else None),
                     R(m.get("yld")), ya, len(ys) if ya is not None else 0, cyc, grp, m.get("streak"), R(d.get("mcap") or 0, 0)])
    rows.sort(key=lambda r: -(r[16] or 0))
    out = {"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "cols": ["代號", "名稱", "產業", "市場", "股價", "漲跌%", "便宜價", "合理價", "昂貴價", "區間", "殖利率", "平均殖利率", "平均年數", "景氣循環", "成分(1台灣50/2中型100)", "連續配息年", "市值(億)"],
           "cyc": {"ind": CYC_IND, "code": CYC_CODE},
           "src": {"t50": [len(t50), n50, d50], "m100": [len(m100), n100, d100]},
           "note": "便宜/合理/昂貴價＝股利法、本益比法、股價淨值比法三法平均(每檔自己的歷史);平均殖利率＝已過完年度的現金股利÷年底股價,至少 3 年才算",
           "stocks": rows}
    with open(os.path.join(DATA, "stk_screen.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("stk_screen:", len(rows), "檔,有估價", sum(1 for r in rows if r[6]), "檔,台灣50", len(t50), "中型100", len(m100))


if __name__ == "__main__":
    main()
