"""量化評分(價值/成長/獲利/財務健康/股利,A+～D)+ 個股分析資料檔 + 月營收排行 + 搜尋名單
輸入:fund/fundamentals.json、experts.json、stock_div.json、ratings.json、chips(raw/detail.json)、value_picks.json、heatmap.json
輸出:data/scores.json、data/rev_rank.json、data/names.json、data/stk/{代號}.json
"""
import json, os, sys, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh, shares
DATA = fh.DATA
L = lambda n, d=None: (json.load(open(os.path.join(DATA, n))) if os.path.exists(os.path.join(DATA, n)) else d)
F = L("fund/fundamentals.json")["companies"]; EX = L("experts.json", {"stocks": {}})["stocks"]; DV = L("stock_div.json", {"stocks": {}, "years": []})
RT = L("ratings.json", {"items": []})["items"]; CH = L("chips/raw/detail.json", {}); CS = L("chips.json", {"stocks": {}})["stocks"]
VPj = L("value_picks.json", {"top": [], "others": []}); VP = {x["id"]: x for x in VPj.get("top", []) + VPj.get("others", []) if isinstance(x, dict) and "id" in x}
HM = {x[0]: x for x in L("heatmap.json", {"items": []})["items"]}
OUT = os.path.join(DATA, "stk"); os.makedirs(OUT, exist_ok=True)
FIX = shares.par_fix(F)          # 非 10 元面額:{代號: 實際股數}
def cashA(c, e):
    """每股現金股利;非 10 元面額改用「發放總額 ÷ 目前股數」(面額變更前的每股股利會失真)"""
    if not e: return None
    if c in FIX and e.get("tot"): return e["tot"] / FIX[c]
    return e.get("cash")
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

def qtl(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs: return None
    k = (len(xs) - 1) * q; f = int(k); c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)

def valuation(f, px, cash_hist, sh=None):
    """三種方法算 便宜/合理/昂貴 價:股利法、本益比法、股價淨值比法"""
    t = f.get("ttm") or {}; ys = sorted(f["y"], key=int); out = {}
    cs = [v for v in cash_hist if v and v > 0]
    if len(cs) >= 3:
        a = sum(cs) / len(cs); out["div"] = [round(a * 15, 2), round(a * 20, 2), round(a * 30, 2)]
    pes = [f["pxY"].get(y) / f["y"][y]["eps"] for y in ys if f.get("pxY", {}).get(y) and (f["y"][y].get("eps") or 0) > 0]
    eps = t["niP"] * 1000 / sh if sh and t.get("niP") is not None else t.get("eps")
    if eps and eps > 0 and len(pes) >= 4:
        out["pe"] = [round(eps * qtl(pes, .2), 2), round(eps * qtl(pes, .5), 2), round(eps * qtl(pes, .8), 2)]
    def bps(d): return d["eqP"] * 10 / d["cap"] if d.get("eqP") and d.get("cap") else None
    pbs = [] if sh else [f["pxY"].get(y) / bps(f["y"][y]) for y in ys if f.get("pxY", {}).get(y) and bps(f["y"][y]) and bps(f["y"][y]) > 0]
    b = t["eqP"] * 1000 / sh if sh and t.get("eqP") else bps(t)
    if b and b > 0 and len(pbs) >= 4:
        out["pb"] = [round(b * qtl(pbs, .2), 2), round(b * qtl(pbs, .5), 2), round(b * qtl(pbs, .8), 2)]
    if not out: return None
    avg = [round(sum(v[i] for v in out.values()) / len(out), 2) for i in range(3)]
    zone = "便宜" if px <= avg[0] else "合理" if px <= avg[1] else "偏貴" if px <= avg[2] else "昂貴"
    return dict(m=out, avg=avg, zone=zone)

def checks(f, divs5):
    """十項體質檢查:回傳 [[項目, 是否正常, 數值, 說明], ...]"""
    ys = sorted(f["y"], key=int); Y = lambda k: [f["y"][y].get(k) for y in ys]; t = f.get("ttm") or {}
    fin = f.get("fmt") != "gen"; L5 = ys[-5:]; g5 = lambda k: [f["y"][y].get(k) for y in L5]
    eps = Y("eps"); pos = sum(1 for e in eps if e is not None and e > 0)
    ni5 = sum(v or 0 for v in g5("niP")); cfi5 = sum(v or 0 for v in g5("cfi")); cfo5 = sum(v or 0 for v in g5("cfo"))
    rein = -cfi5 / ni5 * 100 if ni5 > 0 else None
    cap = (t.get("cap") or 0) / 1e5
    roes = [ratio(f["y"][y].get("niP"), f["y"][y].get("eqP")) for y in L5]; roes = [r for r in roes if r is not None]
    roe5 = sum(roes) / len(roes) if roes else None
    debt = ratio(t.get("tl"), t.get("ta")); cur = ratio(t.get("ca"), t.get("cl"))
    rev = Y("rev"); rg = [ratio(rev[i] - rev[i - 1], rev[i - 1]) for i in range(len(rev) - 3, len(rev)) if i > 0 and rev[i] and rev[i - 1]]
    rg3 = sum(rg) / len(rg) if rg else None
    gms = [ratio(f["y"][y].get("gp"), f["y"][y].get("rev")) for y in L5]; gms = [x for x in gms if x is not None]
    gsd = (sum((x - sum(gms) / len(gms)) ** 2 for x in gms) / len(gms)) ** .5 if len(gms) >= 3 else None
    divok = sum(1 for v in divs5 if v and v > 0)
    C = [["是否年年賺錢", pos == len(eps), f"{pos}/{len(eps)} 年獲利", "近 10 年每一年 EPS 都大於 0，代表經營穩定、不是靠景氣好才賺錢。"],
         ["是否為燒錢慘業", rein is None or rein <= 200, "—" if rein is None else f"盈餘再投資 {rein:.0f}%", "近 5 年投資支出 ÷ 淨利。超過 200% 代表賺的錢不夠拿來擴廠，要一直燒錢才能維持。"],
         ["是否體質虛弱", cap >= 10 and len(ys) >= 5, f"股本 {cap:.0f} 億", "股本太小（低於 10 億）或上市年數太短，抗風險能力較弱。"],
         ["獲利能力好不好", roe5 is not None and roe5 >= 8, "—" if roe5 is None else f"5 年平均 ROE {roe5:.1f}%", "股東權益報酬率 5 年平均至少 8%，代表公司用股東的錢賺錢效率合格。"],
         ["負債是否過高", True if fin else (debt is not None and debt < 60), "金融業不適用" if fin else ("—" if debt is None else f"負債比 {debt:.1f}%"), "負債比超過 60% 代表借錢比例高，景氣反轉時風險大（銀行、保險本來就高，不列入）。"],
         ["短期償債能力", True if fin else (cur is not None and cur >= 100), "金融業不適用" if fin else ("—" if cur is None else f"流動比率 {cur:.0f}%"), "流動比率低於 100% 代表一年內要還的錢比手上能變現的資產還多。"],
         ["賺的是不是真錢", ni5 <= 0 or cfo5 >= ni5 * .8, "—" if ni5 <= 0 else f"現金流 ÷ 淨利 {cfo5 / ni5:.2f} 倍", "近 5 年營業現金流至少要有淨利的 8 成，否則帳上賺錢、口袋卻沒錢。"],
         ["營收是否衰退", rg3 is None or rg3 >= -5, "—" if rg3 is None else f"近 3 年平均 {rg3:+.1f}%", "近 3 年營收平均年減超過 5%，代表生意在萎縮。"],
         ["毛利率是否穩定", True if fin or gsd is None else gsd <= 8, "金融業不適用" if fin else ("—" if gsd is None else f"5 年波動 {gsd:.1f} 個百分點"), "毛利率上下波動太大，代表產品沒有定價能力或受景氣影響很深。"],
         ["配息是否穩定", divok >= 5, f"近 5 年配息 {divok}/5 年", "近 5 年每年都有配現金股利，存股才能穩定領息。"]]
    return C

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
        cash = cashA(c, d.get(lastY)) if lastY else None
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
    # ---- 主力動向(法人＋大戶＋融資)----
    HV = {c: (HM.get(c) or [0] * 7)[6] or 1 for c in U}
    pa = pct_rank({c: (CS.get(c) or {}).get("a20", 0) / (HV[c] * 20) for c in U}); pf = pct_rank({c: (CS.get(c) or {}).get("f5", 0) / (HV[c] * 5) for c in U})
    pm = pct_rank({c: (CS.get(c) or {}).get("mg20p") for c in U}, False); pb = pct_rank({c: (CS.get(c) or {}).get("bigW") for c in U})
    chip = {}
    for c in U:
        parts = [pa.get(c, 50), pf.get(c, 50), pm.get(c, 50)] + ([pb[c]] if c in pb else [])
        v = round(sum(parts) / len(parts)); chip[c] = [v, "主力買超" if v >= 80 else "偏多" if v >= 60 else "中性" if v >= 40 else "偏空" if v >= 20 else "主力賣超"]
    # ---- 估價三法 + 十項體質 ----
    VAL, CHK = {}, {}
    yrs = DV.get("years", [])[:-1][-5:]
    for c in U:
        d = (DV["stocks"].get(c) or {}).get("y", {}); cash5 = [cashA(c, d.get(y)) for y in yrs]
        VAL[c] = valuation(F[c], F[c]["px"], cash5, FIX.get(c)); CHK[c] = checks(F[c], cash5)
    # ---- 輸出:評分總表(篩選器用)----
    sc = {c: [F[c]["name"], F[c].get("ind"), F[c]["px"], *scores[c], R(M[c]["yld"], 2), R(M[c]["pe"], 1), R(M[c]["roe"], 1), chip[c][0], sum(1 for x in CHK[c] if not x[1]), (VAL[c] or {}).get("zone"), M[c]["streak"]] for c in U}
    fh.save(os.path.join(DATA, "scores.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), cols=["名稱", "產業", "股價", "價值", "成長", "獲利", "健康", "股利", "總評", "殖利率", "本益比", "ROE", "主力", "體質警示數", "估價", "連續配息"], stocks=sc,
                    note="各面向為全市場百分位(0～100):價值＝本益比、股價淨值比、殖利率;成長＝近3年營收、近5年EPS、近3月營收年增;獲利＝ROE、毛利率、營益率;健康＝負債比、流動比率、現金流品質;股利＝殖利率、連續配息,配發率>100%扣分"))
    # ---- 定存股名單:十項體質最多 1 項警示、連續配息 ≥5 年、有估價 ----
    dc = []
    for c in U:
        w = sum(1 for x in CHK[c] if not x[1]); v = VAL[c]
        if w <= 1 and M[c]["streak"] >= 5 and v and M[c]["yld"]:
            dc.append([c, F[c]["name"], F[c].get("ind"), F[c]["px"], *v["avg"], v["zone"], R(M[c]["yld"], 2), M[c]["streak"], w, scores[c][5]])
    zo = {"便宜": 0, "合理": 1, "偏貴": 2, "昂貴": 3}
    dc.sort(key=lambda x: (zo[x[7]], -x[8]))
    fh.save(os.path.join(DATA, "dingcun.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), cols=["代號", "名稱", "產業", "股價", "便宜價", "合理價", "昂貴價", "目前位置", "殖利率", "連續配息", "體質警示", "總評"], stocks=dc,
                    note="條件：十項體質檢查最多 1 項警示、連續配息至少 5 年；便宜／合理／昂貴價為股利法、本益比法、股價淨值比法三種估價的平均。"))
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
                   om=[R(ratio(f["y"][y].get("op"), f["y"][y].get("rev")), 1) for y in ys], debt=[R(ratio(f["y"][y].get("tl"), f["y"][y].get("ta")), 1) for y in ys],
                   bps=[R(f["y"][y]["eqP"] * 10 / f["y"][y]["cap"], 2) if f["y"][y].get("eqP") and f["y"][y].get("cap") else None for y in ys], pxY=[f.get("pxY", {}).get(y) for y in ys])
        d = (DV["stocks"].get(c) or {}).get("y", {})
        dv = [[y, R(d[y].get("cash"), 3), R(d[y].get("stk"), 3), d[y].get("pay"), R(cashA(c, d[y]) / f["px"] * 100, 2) if cashA(c, d[y]) and f["px"] else None] for y in DV.get("years", []) if y in d]
        vp = VP.get(c); hm = HM.get(c)
        doc = dict(c=c, n=f["name"], ind=f.get("ind"), mkt=f.get("mkt"), px=f["px"], chg=hm[4] if hm else None, mcap=hm[3] if hm else None, ttmL=f.get("ttmLabel"),
                   s=scores[c], chip=chip[c], val=VAL[c], chk=CHK[c], bpsT=R(t["eqP"] * 1000 / FIX[c], 2) if c in FIX and t.get("eqP") else R(t["eqP"] * 10 / t["cap"], 2) if t.get("eqP") and t.get("cap") else None, m={k: R(m[k], 2) for k in ("pe", "pb", "yld", "roe", "gm", "om", "debt", "cur", "revG3", "epsG", "yoy3", "cfoQ", "pay")} | dict(streak=m["streak"], eps=R(t["niP"] * 1000 / FIX[c], 2) if c in FIX and t.get("niP") is not None else t.get("eps")),
                   fin=fin, rv=(m["rs"] or {}).get("ser", [])[-24:], dv=dv, ch=CH.get(c), cs=CS.get(c), rt=rtg.get(c, [])[:10], ex=EX.get(c, {}).get("hit", []),
                   vp=dict(rank=vp.get("rank"), score=vp.get("score"), zone=vp.get("zone"), band=vp.get("band"), mos=vp.get("mos"), iv=vp.get("iv"), why=vp.get("why")) if vp else None)
        fh.save(os.path.join(OUT, f"{c}.json"), doc); n += 1
    print(f"定存股 {len(dc)} 檔;scores.json {len(sc)} 檔;rev_rank.json {ym} {len(rr)} 檔(近2年新高 {sum(1 for v in rr.values() if v[7])});names {len(names)};stk/ {n} 檔")

if __name__ == "__main__":
    main()
