"""綜合評分 1～10 + 大戶吸籌指標 -> data/smart.json
綜合評分(類似 TipRanks Smart Score,自行定義):
  量化總評 30%、法人籌碼 15%、日線技術 20%、估價位置 20%、分析師目標價空間 15%(沒有法人目標價時權重平均分給其他項)
  扣分:處置股 −20、注意股 −10、其他風險旗標各 −6(最多 −25)、近 60 天董監大股東申報轉讓 −5
大戶吸籌(券商分點有驗證碼不抓,改用公開資料合成):
  外資＋投信 5 日買超占 5 日成交量比例、千張大戶持股比例週變化、借券賣出 5 日變化(減少加分)、融資 20 日變化(散戶下車加分)
  各項取全市場百分位後平均;≥80 大戶吸籌、≤20 大戶出貨
"""
import json, os, sys, datetime as dt, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA
L = lambda n, d=None: json.load(open(os.path.join(DATA, n))) if os.path.exists(os.path.join(DATA, n)) else d

def pct_rank(d, hi=True):
    v = sorted((x for x in d.values() if x is not None)); n = len(v)
    if n < 10: return {}
    import bisect
    return {k: round((bisect.bisect_right(v, x) if hi else n - bisect.bisect_left(v, x)) / n * 100) for k, x in d.items() if x is not None}

def main():
    S = (L("scores.json", {}) or {}).get("stocks", {}); T = (L("tech.json", {}) or {}).get("s", {})
    RK = L("risk.json", {}) or {}; K = (L("chips.json", {}) or {}).get("stocks", {})
    hm = {x[0]: x for x in (L("heatmap.json", {}) or {}).get("items", [])}
    cut = (dt.date.today() - dt.timedelta(days=120)).isoformat(); tp = {}
    for x in (L("ratings.json", {}) or {}).get("items", []):
        if x.get("tp") and x["d"] >= cut and x["id"] not in tp: tp[x["id"]] = x["tp"]          # 最新一筆
    cut60 = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    ins = {x["c"] for x in (L("events.json", {}) or {}).get("insider", []) if x.get("d", "") >= cut60}
    ZV = {"便宜": 90, "合理": 70, "偏貴": 40, "昂貴": 20}
    out = {}
    for c, s in S.items():
        px = s[2]; q, ch, va = s[8], s[12], ZV.get(s[14], 50); te = T[c][0] if c in T else 50
        an = max(0, min(100, 50 + (tp[c] / px - 1) * 100 * 1.5)) if c in tp and px else None
        W = [(q, .30), (ch, .15), (te, .20), (va, .20)] + ([(an, .15)] if an is not None else [])
        base = sum(v * w for v, w in W if v is not None) / sum(w for v, w in W if v is not None)
        f = (RK.get("flags") or {}).get(c, []); pen = 0
        for x in f: pen += 20 if x.startswith("處置") else 10 if x.startswith("注意") else 6
        pen = min(pen, 25) + (5 if c in ins else 0)
        sc = max(1, min(10, round((base - pen) / 10)))
        out[c] = [sc, q, ch, round(te), va, round(an) if an is not None else None, pen, None]
    # 大戶吸籌
    liq = {c for c, x in hm.items() if (x[6] or 0) >= 500}
    a = {c: ((K[c].get("f5") or 0) + (K[c].get("t5") or 0)) / (hm[c][6] * 5) for c in liq if c in K and hm[c][6]}
    b = {c: K[c].get("bigW") for c in liq if c in K and K[c].get("bigW") is not None}
    rs = (RK.get("s") or {}); sb = {c: rs[c][1] for c in liq if c in rs and rs[c][1] is not None}
    mg = {c: K[c].get("mg20p") for c in liq if c in K and K[c].get("mg20p") is not None}
    P = [pct_rank(a), pct_rank(b), pct_rank(sb, hi=False), pct_rank(mg, hi=False)]
    whale = {}
    for c in liq:
        v = [p[c] for p in P if c in p]
        if len(v) >= 2: whale[c] = round(st.mean(v))
    for c, w in whale.items():
        if c in out: out[c][7] = w
    top = sorted(whale.items(), key=lambda x: -x[1])[:60]
    wl = [[c, (S.get(c) or [hm[c][1]])[0], w, round(a.get(c, 0) * 100, 1), b.get(c), sb.get(c), mg.get(c)] for c, w in top]
    fh.save(os.path.join(DATA, "smart.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), s=out, whale=wl,
            cols=["綜合評分1-10", "量化總評", "法人籌碼", "日線技術", "估價位置", "分析師空間", "風險扣分", "大戶吸籌"],
            wcols=["代號", "名稱", "大戶吸籌", "法人5日買超占量%", "千張大戶週變化", "借券5日%", "融資20日%"],
            note="綜合評分與大戶吸籌為本站依公開資料自行計算的參考指標，不是投資建議"))
    dist = {k: sum(1 for v in out.values() if v[0] == k) for k in range(1, 11)}
    print("smart.json:", len(out), "檔;分數分布", dist, ";大戶吸籌前 3", [x[:3] for x in wl[:3]])

if __name__ == "__main__":
    main()
