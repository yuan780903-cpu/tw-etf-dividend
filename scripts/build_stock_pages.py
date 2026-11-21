"""量化評分(價值/成長/獲利/財務健康/股利,A+～D)+ 個股分析資料檔 + 月營收排行 + 搜尋名單
輸入:fund/fundamentals.json、experts.json、stock_div.json、ratings.json、chips(raw/detail.json)、value_picks.json、heatmap.json
輸出:data/scores.json、data/rev_rank.json、data/names.json、data/stk/{代號}.json
"""
import json, os, sys, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA
L = lambda n, d=None: (json.load(open(os.path.join(DATA, n))) if os.path.exists(os.path.join(DATA, n)) else d)
F = L("fund/fundamentals.json")["companies"]; EX = L("experts.json", {"stocks": {}})["stocks"]; DV = L("stock_div.json", {"stocks": {}, "years": []})
RT = L("ratings.json", {"items": []})["items"]; CH = L("chips/raw/detail.json", {}); CS = L("chips.json", {"stocks": {}})["stocks"]
VPj = L("value_picks.json", {"top": [], "others": []}); VP = {x["id"]: x for x in VPj.get("top", []) + VPj.get("others", []) if isinstance(x, dict) and "id" in x}
HM = {x[0]: x for x in L("heatmap.json", {"items": []})["items"]}
OUT = os.path.join(DATA, "stk"); os.makedirs(OUT, exist_ok=True)
R = lambda x, n=2: None if x is None else round(x, n)
def ratio(a, b): return None if a is None or not b else a / b * 100

def rev_stats(rows):
    """rows: [[yyyymm, 當月, 去年當月, 累計, 去年累計]] 新→舊"""
    rows = sorted([r for r in rows if r[1] is not None], key=lambda r: r[0])
    if not rows: return None
    last = rows[-1]; prev = rows[-2] if len(rows) > 1 else None
    yoy = ratio(last[1] - last[2], last[2]) if last[2] else None
    mom = ratio(last[1] - prev[1], prev[1]) if prev and prev[1] else None
    cum = ratio(last[3] - last[4], last[4]) if last[3] and last[4] else None
    hi = len(rows) >= 13 and last[1] > max(r[1] for r in rows[:-1])
    y3 = rows[-3:]; s3, p3 = sum(r[1] for r in y3), sum((r[2] or 0) for r in y3)
    streak = 0
    for r in reversed(rows):
        if r[2] and r[1] > r[2]: streak += 1
        else: break
    return dict(ym=last[0], rev=last[1], yoy=R(yoy, 1), mom=R(mom, 1), cum=R(cum, 1), hi=hi, yoy3=R(ratio(s3 - p3, p3), 1) if p3 else None, up=streak, n=len(rows),
                ser=[[r[0], R(r[1] / 1e5, 2), R(ratio(r[1] - r[2], r[2]), 1) if r[2] else None] for r in rows])

def pct_rank(vals, higher=True):
    """回傳 {code: 0~100 百分位};缺值不給(之後補 30)"""
    xs = sorted((v, c) for c, v in vals.items() if v is not None)
    n = len(xs); out = {}
    for i, (v, c) in enumerate(xs): out[c] = (i / (n - 1) * 100 if n > 1 else 50)
    return out if higher else {c: 100 - p for c, p in out.items()}

def grade(s):
    for t, g in ((90, "A+"), (80, "A"), (70, "A-"), (60, "B+"), (50, "B"), (40, "B-"), (30, "C+"), (20, "C"), (10, "C-")):
        if s >= t: return g
    return "D"

def main():
    lastY = DV["years"][-2] if len(DV.get("years", [])) >= 2 else None       # 最近完整股利年度
    U = [c for c, f in F.items() if f.get("px") and f.get("ttm")]
    M = {}
    for c in U:
        f = F[c]; t = f["ttm"]; e = EX.get(c, {}); d = (DV["stocks"].get(c) or {}).get("y", {})
        cash = (d.get(lastY) or {}).get("cash") if lastY else None
        yld = cash / f["px"] * 100 if cash and f["px"] else 0.0
        streak = 0
        for y in reversed(DV.get("years", [])[:-1]):
            if (d.get(y) or {}).get("cash", 0) > 0: streak += 1
            else: break
        ys = [str(y) for y in sorted(int(k) for k in f["y"])][-5:]
        cfo = sum((f["y"][y].get("cfo") or 0) for y in ys); ni = sum((f["y"][y].get("niP") or 0) for y in ys)
        rs = rev_stats(f.get("rev") or [])
        epsG = e.get("epsG5"); epsG = max(-100, min(epsG, 200)) if epsG is not None else None
        M[c] = dict(pe=e.get("pe") if (e.get("pe") or 0) > 0 else None, pb=e.get("pb"), yld=yld, roe=e.get("roe"), gm=e.get("gm"), om=e.get("om"), debt=e.get("debt"), cur=e.get("cur"),
                    revG3=e.get("revG3"), epsG=epsG, yoy3=rs["yoy3"] if rs else None, cfoQ=cfo / ni if ni > 0 else None, streak=streak, pay=(d.get(lastY) or {}).get("pay") if lastY else None, rs=rs)
    P = {k: pct_rank({c: M[c][k] for c in U}, hi) for k, hi in (("pe", False), ("pb", False), ("yld", True), ("roe", True), ("gm", True), ("om", True), ("debt", False), ("cur", True),
                                                                 ("revG3", True), ("epsG", True), ("yoy3", True), ("cfoQ", True), ("streak", True))}
    g = lambda k, c: P[k].get(c, 30)
    scores = {}
    for c in U:
        m = M[c]
        v = (g("pe", c) + g("pb", c) + g("yld", c)) / 3
        gr = (g("revG3", c) + g("epsG", c) + g("yoy3", c)) / 3
        p = (g("roe", c) + g("gm", c) + g("om", c)) / 3
        h = (g("debt", c) + g("cur", c) + g("cfoQ", c)) / 3
        dv = 0 if not m["yld"] else max(0, (g("yld", c) * .6 + g("streak", c) * .4) - (20 if (m["pay"] or 0) > 100 else 0))
        s = [round(v), round(gr), round(p), round(h), round(dv)]; tot = round(sum(s) / 5)
        scores[c] = s + [tot]
    # 總分再做一次百分位,讓總評分佈均勻
    TP = pct_rank({c: scores[c][5] for c in U})
    for c in U: scores[c][5] = round(TP[c])
    # ---- 輸出:評分總表(篩選器用)----
    sc = {c: [F[c]["name"], F[c].get("ind"), F[c]["px"], *scores[c], R(M[c]["yld"], 2), R(M[c]["pe"], 1), R(M[c]["roe"], 1)] for c in U}
    fh.save(os.path.join(DATA, "scores.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), cols=["名稱", "產業", "股價", "價值", "成長", "獲利", "健康", "股利", "總評", "殖利率", "本益比", "ROE"], stocks=sc,
                    note="各面向為全市場百分位(0～100):價值＝本益比、股價淨值比、殖利率;成長＝近3年營收、近5年EPS、近3月營收年增;獲利＝ROE、毛利率、營益率;健康＝負債比、流動比率、現金流品質;股利＝殖利率、連續配息,配發率>100%扣分"))
    # ---- 月營收排行 ----
    rows = {c: M[c]["rs"] for c in U if M[c]["rs"]}
    from collections import Counter
    ym = Counter(r["ym"] for r in rows.values()).most_common(1)[0][0] if rows else None
    rr = {c: [F[c]["name"], F[c].get("ind"), F[c]["px"], R(r["rev"] / 1e5, 2), r["yoy"], r["mom"], r["cum"], int(r["hi"]), r["up"]] for c, r in rows.items() if r["ym"] == ym}
    fh.save(os.path.join(DATA, "rev_rank.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), ym=ym, cols=["名稱", "產業", "股價", "營收(億)", "年增%", "月增%", "累計年增%", "近2年新高", "年增連續月數"], stocks=rr))
    # ---- 搜尋名單(股票 + ETF)----
    names = [[c, F[c]["name"], F[c].get("ind") or "", F[c].get("mkt") or ""] for c in sorted(F)]
    try:
        for e in L("summary.json", {"etfs": []}).get("etfs", []): names.append([e["id"], e["name"], "ETF", "ETF"])
    except Exception: pass
    fh.save(os.path.join(DATA, "names.json"), names)
    # ---- 個股資料檔 ----
    rtg = {}
    for x in RT: rtg.setdefault(x["id"], []).append([x["d"], x["src"], x["act"], x.get("tp"), x.get("r"), x.get("u"), x.get("media"), x.get("chg"), x.get("eps")])
    n = 0
    for c in U:
        f = F[c]; t = f["ttm"]; m = M[c]; ys = sorted(f["y"], key=int)
        Y = lambda k, div=1, nd=2: [R((f["y"][y].get(k) / div) if f["y"][y].get(k) is not None else None, nd) for y in ys]
        fin = dict(y=ys, rev=Y("rev", 1e5), ni=Y("niP", 1e5), eps=Y("eps", 1, 2), cfo=Y("cfo", 1e5),
                   roe=[R(ratio(f["y"][y].get("niP"), f["y"][y].get("eqP")), 1) for y in ys], gm=[R(ratio(f["y"][y].get("gp"), f["y"][y].get("rev")), 1) for y in ys],
                   om=[R(ratio(f["y"][y].get("op"), f["y"][y].get("rev")), 1) for y in ys], debt=[R(ratio(f["y"][y].get("tl"), f["y"][y].get("ta")), 1) for y in ys])
        d = (DV["stocks"].get(c) or {}).get("y", {})
        dv = [[y, R(d[y].get("cash"), 3), R(d[y].get("stk"), 3), d[y].get("pay"), R(d[y]["cash"] / f["px"] * 100, 2) if d[y].get("cash") and f["px"] else None] for y in DV.get("years", []) if y in d]
        vp = VP.get(c); hm = HM.get(c)
        doc = dict(c=c, n=f["name"], ind=f.get("ind"), mkt=f.get("mkt"), px=f["px"], chg=hm[4] if hm else None, mcap=hm[3] if hm else None, ttmL=f.get("ttmLabel"),
                   s=scores[c], m={k: R(m[k], 2) for k in ("pe", "pb", "yld", "roe", "gm", "om", "debt", "cur", "revG3", "epsG", "yoy3", "cfoQ", "pay")} | dict(streak=m["streak"], eps=t.get("eps")),
                   fin=fin, rv=(m["rs"] or {}).get("ser", [])[-24:], dv=dv, ch=CH.get(c), cs=CS.get(c), rt=rtg.get(c, [])[:10], ex=EX.get(c, {}).get("hit", []),
                   vp=dict(rank=vp.get("rank"), score=vp.get("score"), zone=vp.get("zone"), band=vp.get("band"), mos=vp.get("mos"), iv=vp.get("iv"), why=vp.get("why")) if vp else None)
        fh.save(os.path.join(OUT, f"{c}.json"), doc); n += 1
    print(f"scores.json {len(sc)} 檔;rev_rank.json {ym} {len(rr)} 檔(近2年新高 {sum(1 for v in rr.values() if v[7])});names {len(names)};stk/ {n} 檔")

if __name__ == "__main__":
    main()
