"""三大法人買賣超(上市＋上櫃)-> data/inst.json
上市:證交所 BFI82U(外資＝外資及陸資不含外資自營商＋外資自營商;自營商＝自行買賣＋避險)
上櫃:櫃買 insti/summary(可查歷史,首次回補 25 個交易日;歷史快取在 data/inst_raw.json)
另算 5 日、20 日累計與連續買／賣超天數(單位:億元)
"""
import json, os, sys, time, datetime as dt, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh, net  # noqa: F401  (net:證交所 cookie/307)
DATA = fh.DATA; RAWP = os.path.join(DATA, "inst_raw.json")
UA = {"User-Agent": "Mozilla/5.0"}
N = lambda x: float(str(x).replace(",", "").strip() or 0)

def get(u):
    for k in range(3):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read())
        except Exception as e:
            if k == 2: print("  失敗", u[:80], e)
            time.sleep(2 + 3 * k)

def twse(d):
    j = get(f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate={d}&type=day&response=json")
    if not j or j.get("stat") != "OK" or j.get("date") != d: return None
    o = {"fi": 0, "it": 0, "dl": 0, "tot": 0}
    for r in j["data"]:
        v = N(r[3]) / 1e8
        if r[0].startswith("外資"): o["fi"] += v
        elif r[0].startswith("投信"): o["it"] += v
        elif r[0].startswith("自營商"): o["dl"] += v
        elif r[0].startswith("合計"): o["tot"] = v
    return {k: round(v, 2) for k, v in o.items()}

def tpex(d):
    j = get(f"https://www.tpex.org.tw/www/zh-tw/insti/summary?type=Daily&date={d[:4]}/{d[4:6]}/{d[6:]}&response=json")
    t = (j or {}).get("tables") or []
    if not t or not t[0].get("data"): return None
    dd = t[0].get("date", "")
    if dd and dd.replace("/", "") != str(int(d[:4]) - 1911) + d[4:]: return None
    o = {}
    for r in t[0]["data"]:
        n, v = r[0].strip(), N(r[3]) / 1e8
        if n == "外資及陸資合計": o["fi"] = v
        elif n == "投信": o["it"] = v
        elif n == "自營商合計": o["dl"] = v
        elif n.startswith("三大法人合計"): o["tot"] = v
    return {k: round(v, 2) for k, v in o.items()} if "tot" in o else None

def otc_index():
    """櫃買指數日線(櫃買中心 indexInfo/inx 月查詢,近 12 個月;舊月份用快取、只重抓本月與上月)→ {YYYY-MM-DD: 收盤}"""
    p = os.path.join(DATA, "otc_idx.json")
    o = json.load(open(p)) if os.path.exists(p) else {}
    t = dt.date.today(); mons = []
    for k in range(12):
        y, m = t.year, t.month - k
        while m <= 0: y, m = y - 1, m + 12
        mons.append((y, m))
    for i, (y, m) in enumerate(mons):
        key = f"{y}-{m:02d}"
        if i >= 2 and any(d.startswith(key) for d in o): continue
        j = get(f"https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?date={y}/{m:02d}/01&response=json")
        try:
            for r in (j or {}).get("tables", [{}])[0].get("data", []):
                d = r[0].replace("/", "-")
                if len(d) == 10: o[d] = round(N(r[4]), 2)
        except Exception as e: print("  櫃買指數", key, e)
        time.sleep(.6)
    o = dict(sorted(o.items())[-300:]); fh.save(p, o)
    return o

def hist(ALL, raw):
    """區間交叉分析用的每日序列 -> data/inst_hist.json
    上市:market.json(約 5 年,取近 500 個交易日)＋今天剛抓、market.json 還沒有的;指數＝加權指數
    上櫃:櫃買中心(近一年);指數＝櫃買指數"""
    ymd = lambda d: f"{d[:4]}-{d[4:6]}-{d[6:]}"
    tw = {r["d"]: [r["fi"], r["it"], r["dl"], r["tot"], r["tx"]] for r in ALL[-500:] if r.get("fi") is not None and r.get("tx")}
    last_tx = ALL[-1]["tx"] if ALL else None
    try: TX = {r[0]: r[4] for r in json.load(open(os.path.join(DATA, "taiex.json")))}    # 今天的加權指數(market.json 還沒更新時)
    except Exception: TX = {}
    for d, o in raw["twse"].items():
        if ymd(d) not in tw and ymd(d) > max(tw, default=""): tw[ymd(d)] = [o["fi"], o["it"], o["dl"], o["tot"], TX.get(ymd(d))]
    OTC = otc_index()
    tp = {ymd(d): [o.get("fi"), o.get("it"), o.get("dl"), o.get("tot"), OTC.get(ymd(d))] for d, o in raw["tpex"].items()}
    pack = lambda S: {"cols": ["d", "fi", "it", "dl", "tot", "ix"], "rows": [[d] + v for d, v in sorted(S.items())]}
    fh.save(os.path.join(DATA, "inst_hist.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), twse=pack(tw), tpex=pack(tp),
            note="單位：億元；ix＝當天收盤指數(上市＝加權指數、上櫃＝櫃買指數),null＝當天指數尚未收錄"))
    print(f"inst_hist.json:上市 {len(tw)} 天、上櫃 {len(tp)} 天(櫃買指數 {sum(1 for v in tp.values() if v[4])} 天)")

def main():
    M = json.load(open(os.path.join(DATA, "market.json"))); C = M["cols"]
    ALL = [dict(zip(C, r)) for r in M["rows"]]
    rows = {r["d"].replace("-", ""): r for r in ALL[-60:]}
    raw = json.load(open(RAWP)) if os.path.exists(RAWP) else {"twse": {}, "tpex": {}}
    for d, r in rows.items():                                # 上市:market.json 已有 → 一律以它為準(證交所事後更正的數字會跟著更新)
        if r.get("fi") is not None and r.get("it") is not None: raw["twse"][d] = {"fi": r["fi"], "it": r["it"], "dl": r["dl"], "tot": r["tot"]}
    today = dt.datetime.utcnow() + dt.timedelta(hours=8); td = today.strftime("%Y%m%d")
    if today.weekday() < 5 and today.hour >= 15:            # 今天收盤後:market.json 可能還沒更新,直接抓
        for k, f in (("twse", twse), ("tpex", tpex)):          # 每次都重抓今天(證交所／櫃買傍晚可能更正)
            o = f(td)
            if o: raw[k][td] = o
    days = sorted({r["d"].replace("-", "") for r in ALL[-250:]} | set(raw["twse"]))[-250:]
    n = 0
    for d in reversed(days):                                  # 上櫃回補(近一年,由新到舊,每次最多 80 天,幾次後補滿)
        if d in raw["tpex"]: continue
        if n >= 80: break
        o = tpex(d)
        if o: raw["tpex"][d] = o
        n += 1; time.sleep(.6)
    raw["twse"] = dict(sorted(raw["twse"].items())[-60:]); raw["tpex"] = dict(sorted(raw["tpex"].items())[-260:])
    fh.save(RAWP, raw)
    hist(ALL, raw)
    def summ(S):
        ks = sorted(S);
        if not ks: return None
        last = S[ks[-1]]; out = {"d": ks[-1], **last}
        for f in ("fi", "it", "dl", "tot"):
            v = [S[k].get(f) for k in ks if S[k].get(f) is not None]
            out[f + "5"] = round(sum(v[-5:]), 2); out[f + "20"] = round(sum(v[-20:]), 2)
            sgn = 1 if (v and v[-1] > 0) else -1; st = 0
            for x in reversed(v):
                if x * sgn > 0: st += 1
                else: break
            out[f + "S"] = st * sgn
            out[f + "H"] = v[-20:]
        return out
    tw, tp = summ(raw["twse"]), summ(raw["tpex"])
    fh.save(os.path.join(DATA, "inst.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), twse=tw, tpex=tp,
            note="單位：億元；外資含外資自營商，自營商含自行買賣與避險；S＝連續買超（正）或賣超（負）天數"))
    print("inst.json:上市", tw and (tw["d"], tw["fi"], tw["it"], tw["dl"], tw["tot"]), "上櫃", tp and (tp["d"], tp["tot"]), "回補上櫃", n, "天")

if __name__ == "__main__":
    main()
