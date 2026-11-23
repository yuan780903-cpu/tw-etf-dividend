"""大師選股回測 -> data/backtest.json
做法(年度換股,避免「偷看答案」):
  每年年底(Y)用「當時已公布」的財報(到 Y-1 年度為止)套用每位大師的條件選股,
  以 Y 年底收盤價買進、持有一年到 Y+1 年底(最後一年持有到今天),等權重,報酬含持有期間領到的現金股利(Y 年度股利)。
比較基準:0050 同期間報酬(含配息)。
限制(網頁會揭露):只含目前仍上市櫃的公司(倖存者偏差,報酬會偏樂觀);董監持股只有最新資料;股利資料自 2021 年起;
  不計交易成本與稅;股票分割依 splits.json 還原,減資等無法還原的異常報酬(單年 >+400% 或 <-95%)剔除。
"""
import json, os, sys, datetime as dt, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import build_experts as BE, fetch_history as fh
DATA = fh.DATA
L = lambda n, d=None: json.load(open(os.path.join(DATA, n))) if os.path.exists(os.path.join(DATA, n)) else d

def main():
    F = BE.F["companies"]; Y = BE.Y; SPL = L("splits.json", {}) or {}
    DV = BE.divs(); dpct = BE.director_pct()
    px50 = L("prices/0050.json", []) or []; dv50 = L("dividends/0050.json", []) or []
    def split_factor(c, a, b):          # a<日期<=b 之間的分割,把買進價換算成分割後
        f = 1.0
        for d, r in SPL.get(c, []):
            if a < d <= b: f *= r
        return f
    def ye(rows, y):                    # 某年最後一個收盤
        v = None
        for r in rows:
            if r[0][:4] == y: v = r[4]
        return v
    today = dt.date.today().isoformat()
    forms = [y for y in Y if Y.index(y) >= 5]                     # 需要前 5 個年度的財報才能套用條件
    ids = [e["id"] for e in BE.EXPERTS] + ["consensus"]
    R = {k: {} for k in ids}; bench = {}
    for y0 in forms:
        y1 = str(int(y0) + 1); hold_end = y1 if y1 in Y else "今天"
        fy = str(int(y0) - 1); Yh = [y for y in Y if y <= fy]
        a, b = f"{y0}-12-31", (f"{y1}-12-31" if hold_end != "今天" else today)
        # 基準 0050
        p0 = ye(px50, y0); p1 = ye(px50, y1) if hold_end != "今天" else (px50[-1][4] if px50 else None)
        cash50 = sum(x["cash"] * split_factor("0050", x["ex"], "9999") for x in dv50 if a < x["ex"] <= b)
        bench[y1 if hold_end != "今天" else f"{y1}（至今）"] = round(((p1 + cash50) / p0 - 1) * 100, 1) if p0 and p1 else None
        picks = {k: [] for k in ids}
        for c, d in F.items():
            pxY = d.get("pxY") or {}; t = (d.get("y") or {}).get(fy)
            if not t or not pxY.get(y0) or pxY[y0] < 5: continue
            end = pxY.get(y1) if hold_end != "今天" else d.get("px")
            if not end: continue
            m, test = BE.evaluate(c, d, t, pxY[y0], dpct, DV, {}, Y=Yh)
            if len(Yh) > 5:                                         # 「比上一年度進步」類條件:用前一年度當比較基準
                _, t2 = BE.evaluate(c, d, t, pxY[y0], dpct, DV, {}, Y=Yh[:-1])
                for k in ("osh", "wood"): test[k] = t2[k]
            else:
                for k in ("osh", "wood"): test[k] = [False]
            f = split_factor(c, a, b); buy = pxY[y0] * f
            cash = ((DV.get(c) or {}).get("y", {}).get(y0) or {}).get("cash") if f == 1 else None
            r = (end + (cash or 0)) / buy - 1
            if r > 4 or r < -.95: continue                          # 減資等無法還原的異常
            hit = [k for k, v in test.items() if all(v)]
            for k in hit: picks[k].append((c, r))
            if len(hit) >= 3: picks["consensus"].append((c, r))
        key = y1 if hold_end != "今天" else f"{y1}（至今）"
        for k in ids:
            P = picks[k]
            R[k][key] = [round(st.mean(r for _, r in P) * 100, 1), len(P), [c for c, _ in sorted(P, key=lambda x: -x[1])[:5]]] if P else [None, 0, []]
    out = {}
    full = [k for k in bench if "至今" not in k]
    for k in ids:
        yrs = R[k]; rs = [yrs[y][0] for y in full if yrs[y][0] is not None]
        cum = 1.0
        for x in rs: cum *= 1 + x / 100
        cagr = (cum ** (1 / len(rs)) - 1) * 100 if rs else None
        win = sum(1 for y in full if yrs[y][0] is not None and bench[y] is not None and yrs[y][0] > bench[y])
        out[k] = dict(y=yrs, cagr=round(cagr, 1) if cagr is not None else None, cum=round((cum - 1) * 100, 1) if rs else None, win=win, n=len(rs),
                      worst=min(rs) if rs else None, avgN=round(st.mean(yrs[y][1] for y in yrs), 0))
    bc = 1.0
    for y in full:
        if bench[y] is not None: bc *= 1 + bench[y] / 100
    fh.save(os.path.join(DATA, "backtest.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), years=list(bench), bench=bench,
            benchCagr=round((bc ** (1 / len(full)) - 1) * 100, 1) if full else None, benchCum=round((bc - 1) * 100, 1), s=out,
            names={e["id"]: e["name"] for e in BE.EXPERTS} | {"consensus": "大師共識（≥3 位同時選中）"}, nodata={"chenzm": "股利資料自 2021 年起，不足 5 年連續配息，無法回測", "warrentw": "股利資料自 2021 年起，不足 5 年連續配息，無法回測", "sivy": "條件非常嚴格，歷年都沒有公司同時符合"},
            note="每年年底用當時已公布的財報選股、持有一年（最後一年至今）、等權重、含現金股利；不含交易成本。只包含目前仍上市櫃的公司，報酬會偏樂觀（倖存者偏差）。過去績效不代表未來。"))
    print("backtest.json:", ", ".join(f"{k} 年化 {v['cagr']}%" for k, v in list(out.items())[:6]), "… 0050", bench)

if __name__ == "__main__":
    main()
