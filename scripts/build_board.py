"""大盤總表一覽 -> data/board.json
加權指數、櫃買指數、成交金額、漲跌家數、站上 200 日線比例、大盤本益比、外資買賣超、融資餘額、台指期(一般盤＋夜盤)
"""
import json, os, sys, datetime as dt, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; UA = {"User-Agent": "Mozilla/5.0"}
L = lambda n, d=None: json.load(open(os.path.join(DATA, n))) if os.path.exists(os.path.join(DATA, n)) else d
N = lambda x: float(str(x).replace(",", "").replace("%", "")) if str(x).replace(",", "").replace("%", "").replace("-", "", 1).replace(".", "", 1).isdigit() else None
def get(u):
    try: return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read())
    except Exception as e: print("  失敗", u[:70], e); return None
def pct(hist, v):
    h = [x for x in hist if x is not None]
    return round(sum(1 for x in h if x <= v) / len(h) * 100) if h and v is not None else None

def main():
    B = {}
    m = L("market.json"); R = [dict(zip(m["cols"], r)) for r in m["rows"]]; last, prev = R[-1], R[-2]
    hi = max(r["tx"] for r in R)
    B["taiex"] = dict(v=last["tx"], chg=round(last["tx"] - prev["tx"], 2), pct=round((last["tx"] / prev["tx"] - 1) * 100, 2), fromHi=round((last["tx"] / hi - 1) * 100, 1), d=last["d"], spark=[r["tx"] for r in R[-60:]])
    # 櫃買指數
    t = get("https://www.tpex.org.tw/openapi/v1/tpex_index")
    if t:
        a, b = t[-1], t[-2] if len(t) > 1 else None
        cl, ch = N(a["Close"]), N(a["Change"])
        B["otc"] = dict(v=cl, chg=ch, pct=round(ch / (cl - ch) * 100, 2) if cl and ch is not None else None, d=a["Date"], mtd=round((cl / N(t[0]["Open"]) - 1) * 100, 1) if N(t[0]["Open"]) else None, spark=[N(x["Close"]) for x in t])
    # 上市成交金額(近兩個月算 20 日平均)
    today = dt.date.today(); vals = []
    for mm in (today.replace(day=1) - dt.timedelta(days=1), today):
        j = get(f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={mm:%Y%m}01&response=json")
        for r in (j or {}).get("data", []): vals.append((r[0], N(r[2]) / 1e8 if N(r[2]) else None))
    vals = [v for v in vals if v[1]]
    if vals:
        v = vals[-1][1]; avg = sum(x[1] for x in vals[-21:-1]) / max(1, len(vals[-21:-1]))
        B["turn"] = dict(v=round(v), avg20=round(avg), ratio=round(v / avg, 2) if avg else None, spark=[round(x[1]) for x in vals[-40:]])
    # 漲跌家數、站上 200 日線
    br = L("breadth.json")
    if br:
        rows = [dict(zip(br["cols"], r)) for r in br["rows"]]; x = rows[-1]
        B["breadth"] = dict(adv=x["adv"], dec=x["dec"], lu=x["lu"], ld=x["ld"], d=x["d"])
        a2 = [r["a200"] for r in rows]
        B["a200"] = dict(v=x["a200"], pct=pct(a2, x["a200"]), spark=a2[-60:], years=round(len(rows) / 250))
    # 大盤本益比(上市櫃全部公司:總市值 ÷ 近四季稅後淨利),與自己歷年比較
    F = L("fund/fundamentals.json")["companies"]; ys = sorted({y for f in F.values() for y in f.get("y", {})}, key=int)
    cap = sum((f["px"] or 0) * f["ttm"]["cap"] * 100 for f in F.values() if f.get("px") and f.get("ttm") and f["ttm"].get("cap") and f["ttm"].get("niP") is not None)
    ni = sum(f["ttm"]["niP"] * 1000 for f in F.values() if f.get("px") and f.get("ttm") and f["ttm"].get("cap") and f["ttm"].get("niP") is not None)
    hist = []
    for y in ys:
        c = sum(f["pxY"][y] * f["y"][y]["cap"] * 100 for f in F.values() if f.get("pxY", {}).get(y) and f["y"].get(y, {}).get("cap") and f["y"][y].get("niP") is not None)
        n = sum(f["y"][y]["niP"] * 1000 for f in F.values() if f.get("pxY", {}).get(y) and f["y"].get(y, {}).get("cap") and f["y"][y].get("niP") is not None)
        if n > 0: hist.append(round(c / n, 1))
    pe = round(cap / ni, 1) if ni > 0 else None
    B["pe"] = dict(v=pe, pct=pct(hist, pe), hist=hist, years=f"{ys[0]}～{ys[-1]}", lo=min(hist) if hist else None, hi=max(hist) if hist else None)
    # 外資、融資(上市)
    B["foreign"] = dict(v=last["fi"], d5=round(sum(r["fi"] for r in R[-5:] if r["fi"] is not None), 1), spark=[r["fi"] for r in R[-20:]])
    B["margin"] = dict(v=last["mAmt"], chg=round(last["mAmt"] - prev["mAmt"], 1) if prev["mAmt"] else None, d=last["d"], spark=[r["mAmt"] for r in R[-60:]])
    # 台指期:一般盤＋夜盤(近月)
    f = get("https://openapi.taifex.com.tw/v1/DailyMarketReportFut")
    if f:
        tx = [x for x in f if x.get("Contract") == "TX" and x.get("ContractMonth(Week)", "").isdigit()]
        if tx:
            near = min({x["ContractMonth(Week)"] for x in tx})
            def sess(name):
                x = next((y for y in tx if y["ContractMonth(Week)"] == near and y["TradingSession"] == name), None)
                return None if not x else dict(last=N(x["Last"]), chg=N(x["Change"]), pct=N(x["%"]), hi=N(x["High"]), lo=N(x["Low"]), op=N(x["Open"]), vol=N(x["Volume"]), oi=N(x["OpenInterest"]), d=x["Date"])
            day, night = sess("一般"), sess("盤後")
            B["tx"] = dict(month=near, day=day, night=night, basis=round(day["last"] - last["tx"], 2) if day and day["last"] else None)
    B["updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    fh.save(os.path.join(DATA, "board.json"), B)
    print("board.json:", {k: (v.get("v") if isinstance(v, dict) and "v" in v else "…") for k, v in B.items() if k != "updated"})

if __name__ == "__main__":
    main()
