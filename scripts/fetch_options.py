"""期權籌碼 + 台積電 ADR 溢價 -> data/options.json
- 臺指選擇權 P/C Ratio(期交所 OpenAPI PutCallRatio,約 30 個交易日)
- 最大未平倉履約價:近月(月選)與最近週選,買權最大 OI＝壓力、賣權最大 OI＝支撐(DailyMarketReportOpt,一般交易時段)
- 外資選擇權買權/賣權淨未平倉(三大法人-買賣權分計)
- 台積電 ADR 溢價:TSM × 美元兌台幣 ÷ 5 ÷ 2330 收盤 − 1(Yahoo 日線,近 3 個月)
"""
import json, os, sys, csv, io, urllib.request, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; UA = {"User-Agent": "Mozilla/5.0"}
F = lambda x: (lambda s: float(s) if s.replace(".", "", 1).replace("-", "", 1).isdigit() else None)(str(x).replace(",", "").strip())

def raw(u, t=120):
    try: return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t).read().decode("utf-8-sig")
    except Exception as e: print("  失敗", u[:80], e); return None
def J(u):
    r = raw(u); return json.loads(r) if r and r.strip().startswith(("[", "{")) else None

TODAY = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()

def www_csv(u):
    """期交所官網 CSV 下載(Big5,當天收盤後就有;OpenAPI 通常隔天才更新)"""
    try: b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120).read()
    except Exception as e: print("  官網失敗", u[:70], e); return []
    t = b.decode("big5", "ignore")
    if t.lstrip().startswith("<"): return []
    R = list(csv.reader(io.StringIO(t)))
    if len(R) < 2: return []
    H = [h.strip() for h in R[0]]
    return [{H[i]: (r[i].strip() if i < len(r) else "") for i in range(len(H))} for r in R[1:] if len(r) >= len(H) - 2]

_OPT = {}
def opt_today():
    """今天的選擇權每日行情(官網),轉成 OpenAPI DailyMarketReportOpt 的欄位名稱"""
    if "rows" in _OPT: return _OPT["rows"]
    d = f"{TODAY:%Y/%m/%d}"
    rows = [dict(r, 日期=r.get("交易日期", "").replace("/", ""), 未沖銷契約量=r.get("未沖銷契約數", ""))
            for r in www_csv(f"https://www.taifex.com.tw/cht/3/optDataDown?down_type=1&commodity_id=TXO&queryStartDate={d}&queryEndDate={d}") if r.get("契約") == "TXO"]
    _OPT["rows"] = rows; print("  官網選擇權行情", len(rows), "筆", rows[0]["日期"] if rows else "")
    return rows

def max_oi():
    rows = [r for r in opt_today() if r.get("交易時段") == "一般"]
    if not rows:
        t = raw("https://openapi.taifex.com.tw/v1/DailyMarketReportOpt")
        if not t: return None
        rows = [r for r in csv.DictReader(io.StringIO(t)) if r.get("契約") == "TXO" and r.get("交易時段") == "一般"]
    if not rows: return None
    import calendar
    def expiry(e):      # 202612=月選(第 3 個週三)、202611W4=第 4 個週三、202611F3=第 3 個週五
        y, m = int(e[:4]), int(e[4:6]); wd, n = (2, 3) if len(e) == 6 else (2 if e[6] == "W" else 4, int(e[7:]))
        ds = [d for d in range(1, calendar.monthrange(y, m)[1] + 1) if dt.date(y, m, d).weekday() == wd]
        return dt.date(y, m, ds[min(n, len(ds)) - 1])
    today = dt.datetime.strptime(rows[0]["日期"], "%Y%m%d").date()
    exps = sorted({r["到期月份(週別)"].strip() for r in rows}, key=lambda e: expiry(e))
    live = [e for e in exps if expiry(e) > today]
    month = next((e for e in live if len(e) == 6), None); week = next((e for e in live if len(e) > 6), None)
    try: spot = json.load(open(os.path.join(DATA, "board.json")))["taiex"]["v"]
    except Exception: spot = None
    def pick(e):
        if not e: return None
        R = [r for r in rows if r["到期月份(週別)"].strip() == e]
        def side(k):
            L = [(F(r["履約價"]), F(r["未沖銷契約量"]) or 0) for r in R if r["買賣權"] == k and F(r["履約價"]) and (not spot or abs(F(r["履約價"]) / spot - 1) <= .15)]
            L.sort(key=lambda x: -x[1]); return L[:3], sum(x[1] for x in L)
        (c3, ct), (p3, pt) = side("買權"), side("賣權")
        return dict(exp=e, due=expiry(e).isoformat(), call=c3, put=p3, callOI=ct, putOI=pt, pcr=round(pt / ct * 100, 1) if ct else None, d=R[0]["日期"])
    return dict(month=pick(month), week=pick(week))

def inst():
    d = f"{TODAY:%Y/%m/%d}"
    W = www_csv(f"https://www.taifex.com.tw/cht/3/callsAndPutsDateDown?queryStartDate={d}&queryEndDate={d}&commodityId=TXO")
    out = {}
    for r in W:                                  # 官網(當天):外資及陸資的買權/賣權未平倉淨額
        if r.get("商品名稱") == "臺指選擇權" and r.get("身份別", "").startswith("外資"):
            out[r["買賣權別"].lower()] = dict(oi=F(r.get("未平倉口數買賣淨額")), val=F(r.get("未平倉契約金額買賣淨額(千元)")), d=r.get("日期", "").replace("/", ""))
    if out.get("call") and out.get("put"): return out
    d = J("https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersDetailsOfCallsAndPutsBytheDate") or []   # 名稱是「外資及陸資」
    out = {}
    for r in d:
        if r.get("ContractCode") == "臺指選擇權" and str(r.get("Item", "")).startswith("外資"):
            out[r["CallPut"].lower()] = dict(oi=F(r.get("OpenInterest(Net)")), val=F(r.get("ContractValueofOpenInterest(Net)(Thousands)")), d=r.get("Date"))
    return out or None

def yahoo(sym, rng="3mo"):
    try:
        x = json.loads(raw(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"))["chart"]["result"][0]
        off = x["meta"].get("gmtoffset") or 0; c = x["indicators"]["quote"][0]["close"]
        return {dt.datetime.utcfromtimestamp(t + off).strftime("%Y-%m-%d"): v for t, v in zip(x["timestamp"], c) if v}
    except Exception as e: print("  Yahoo 失敗", sym, e); return {}

def adr():
    T, S, X = yahoo("TSM"), yahoo("2330.TW"), yahoo("TWD=X")
    rows, xs = [], sorted(X)
    for d in sorted(S):
        tsm = next((T[k] for k in sorted(T, reverse=True) if k < d), None)          # 前一個美股交易日收盤
        fx = next((X[k] for k in reversed(xs) if k <= d), None)
        if tsm and fx: rows.append([d, round((tsm * fx / 5 / S[d] - 1) * 100, 2), round(tsm, 2), S[d]])
    return rows[-60:]

def main():
    pcr = J("https://openapi.taifex.com.tw/v1/PutCallRatio") or []
    P = sorted([[r["Date"], F(r.get("PutCallOIRatio%")), F(r.get("PutCallVolumeRatio%"))] for r in pcr if r.get("Date")])
    R = opt_today()                              # OpenAPI 還沒有今天 → 用官網今天的行情自己算(和官方算法一致:未平倉只有一般時段、成交量含盤後)
    if R and (not P or R[0]["日期"] > P[-1][0]):
        s = lambda k, cp: sum(F(r.get(k)) or 0 for r in R if r.get("買賣權") == cp)
        co, po, cv, pv = s("未沖銷契約量", "買權"), s("未沖銷契約量", "賣權"), s("成交量", "買權"), s("成交量", "賣權")
        if co and cv: P.append([R[0]["日期"], round(po / co * 100, 2), round(pv / cv * 100, 2)])
    out = dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), pcr=P, oi=max_oi(), inst=inst(), adr=adr(),
               note="P/C Ratio＝賣權未平倉÷買權未平倉×100,高於 100 偏多(法人買賣權避險/看多)、低於 80 偏保守;最大未平倉履約價常被視為短線壓力(買權)與支撐(賣權)")
    fh.save(os.path.join(DATA, "options.json"), out)
    o = out["oi"] or {}; m = o.get("month") or {}
    print("options.json:P/C", P[-1] if P else None, "月選壓力", (m.get("call") or [[None]])[0][0], "支撐", (m.get("put") or [[None]])[0][0], "ADR溢價", out["adr"][-1] if out["adr"] else None)

if __name__ == "__main__":
    main()
