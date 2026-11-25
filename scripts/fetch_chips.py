"""籌碼與熱力圖 -> data/chips.json、data/heatmap.json(個股明細另寫入 data/chips/raw 給個股頁用)
  三大法人個股買賣超:證交所 T86、櫃買 3itrade_hedge(近 20 個交易日,每日一檔快取)
  集保大戶持股:集保 opendata 1-5 股權分散表(每週,累積保留 26 週)
  熱力圖:證交所 STOCK_DAY_ALL、櫃買 daily_close_quotes 的當日漲跌 + 市值(股本 × 股價)
單位:法人買賣超為「張」
"""
import json, os, re, sys, time, csv, io, datetime as dt, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; RAW = os.path.join(DATA, "chips", "raw"); os.makedirs(RAW, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}
TODAY = dt.date.today()
N = lambda x: float(str(x).replace(",", "").strip() or 0) if re.match(r"^-?[\d,.]+$", str(x).replace(",", "").strip() or "x") else 0.0

def get(url, timeout=60, raw=False):
    for i in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
            return b if raw else json.loads(b)
        except Exception as e:
            if i == 2: print("  失敗", url[:90], e); return None
            time.sleep(4 * (i + 1))

def inst_day(d):
    """某日三大法人買賣超(張):{代號: [外資, 投信, 自營, 合計]};非交易日回 None"""
    p = os.path.join(RAW, f"inst_{d:%Y%m%d}.json")
    if os.path.exists(p): return json.load(open(p))
    out = {}
    j = get(f"https://www.twse.com.tw/rwd/zh/fund/T86?date={d:%Y%m%d}&selectType=ALLBUT0999&response=json")
    if not j or j.get("stat") != "OK" or not j.get("data"): return None
    for r in j["data"]:
        c = r[0].strip()
        out[c] = [round((N(r[4]) + N(r[7])) / 1000), round(N(r[10]) / 1000), round(N(r[11]) / 1000), round(N(r[18]) / 1000)]
    time.sleep(3)
    j = get(f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d={d.year - 1911}/{d:%m/%d}")
    for t in (j or {}).get("tables", []):
        for r in t.get("data", []):
            if len(r) >= 24: out[r[0].strip()] = [round(N(r[10]) / 1000), round(N(r[13]) / 1000), round(N(r[22]) / 1000), round(N(r[23]) / 1000)]
    time.sleep(3)
    fh.save(p, out); print(f"  三大法人 {d}: {len(out)} 檔")
    return out

def margin_day(d):
    """某日融資、融券餘額(張):{代號: [融資餘額, 融券餘額]}"""
    p = os.path.join(RAW, f"mg_{d:%Y%m%d}.json")
    if os.path.exists(p): return json.load(open(p))
    out = {}
    j = get(f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={d:%Y%m%d}&selectType=ALL&response=json")
    if not j or j.get("stat") != "OK": return None
    for t in j.get("tables", []):
        if len(t.get("data", [])) > 100:
            for r in t["data"]: out[r[0].strip()] = [int(N(r[6])), int(N(r[12]))]
    time.sleep(3)
    j = get(f"https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&o=json&d={d.year - 1911}/{d:%m/%d}")
    for t in (j or {}).get("tables", []):
        for r in t.get("data", []):
            if len(r) >= 15: out[r[0].strip()] = [int(N(r[6])), int(N(r[14]))]
    time.sleep(3)
    if len(out) < 500: return None
    fh.save(p, out); print(f"  融資融券 {d}: {len(out)} 檔")
    return out

def tdcc():
    """集保股權分散表(最新一週)→ {代號: [千張以上%, 400張以上%, 總人數, 10張以下%]}"""
    b = get("https://opendata.tdcc.com.tw/getOD.ashx?id=1-5", 120, raw=True)
    if not b: return None, None
    rows = list(csv.reader(io.StringIO(b.decode("utf-8-sig", "ignore"))))[1:]
    agg, day = {}, None
    for r in rows:
        if len(r) < 6: continue
        day = r[0]; c = r[1].strip(); lv = int(r[2]); a = agg.setdefault(c, [0.0, 0.0, 0, 0.0])
        pct = N(r[5])
        if lv == 15: a[0] += pct
        if 12 <= lv <= 15: a[1] += pct
        if lv <= 3: a[3] += pct
        if lv == 17: a[2] = int(N(r[3]))
    out = {c: [round(v[0], 2), round(v[1], 2), v[2], round(v[3], 2)] for c, v in agg.items() if re.match(r"^\d{4}$", c)}
    if day: fh.save(os.path.join(RAW, f"tdcc_{day}.json"), out)
    print(f"  集保 {day}: {len(out)} 檔"); return day, out

def quotes():
    """今日收盤與漲跌:{代號: [收盤, 漲跌%, 成交張數]}"""
    q = {}
    import quotes                                  # 官網當日行情優先(OpenAPI 晚上才更新)
    for x in quotes.twse_all():
        c, cl, ch = x.get("Code"), N(x.get("ClosingPrice")), N(x.get("Change"))
        if c and cl: q[c] = [cl, round(ch / (cl - ch) * 100, 2) if cl - ch else 0, round(N(x.get("TradeVolume")) / 1000)]
    for x in quotes.tpex_all():
        c, cl, ch = x.get("SecuritiesCompanyCode"), N(x.get("Close")), N(x.get("Change"))
        if c and cl: q[c] = [cl, round(ch / (cl - ch) * 100, 2) if cl - ch else 0, round(N(x.get("TradingShares")) / 1000)]
    return q

def main():
    fp = os.path.join(DATA, "fund", "fundamentals.json")
    if not os.path.exists(fp): print("沒有財報檔(雲端快取尚未建立),籌碼沿用上一版"); return
    F = json.load(open(fp))["companies"]
    days, d = [], TODAY
    while len(days) < 20 and (TODAY - d).days < 40:
        if d.weekday() < 5:
            r = inst_day(d)
            if r: days.append((d, r))
        d -= dt.timedelta(days=1)
    days.sort(key=lambda x: x[0])
    mg = [(x[0], margin_day(x[0])) for x in days]; mg = [(dd, r) for dd, r in mg if r]
    for f in os.listdir(RAW):
        if f.startswith("mg_") and f[3:11] < (days[0][0].strftime("%Y%m%d") if days else "0"): os.remove(os.path.join(RAW, f))
    # 只保留近 30 個交易日的快取
    keep = {f"inst_{x[0]:%Y%m%d}.json" for x in days}
    for f in os.listdir(RAW):
        if f.startswith("inst_") and f not in keep and f < min(keep, default="z"): os.remove(os.path.join(RAW, f))
    day, td = tdcc()
    tfiles = sorted(f for f in os.listdir(RAW) if f.startswith("tdcc_"))
    for f in tfiles[:-26]: os.remove(os.path.join(RAW, f))
    tdh = [(f[5:13], json.load(open(os.path.join(RAW, f)))) for f in sorted(os.listdir(RAW)) if f.startswith("tdcc_")]
    # 個股籌碼摘要
    stocks = {}
    codes = {c for _, r in days for c in r} | set(F)
    for c in codes:
        if not re.match(r"^\d{4}$", c): continue
        ser = [r.get(c, [0, 0, 0, 0]) for _, r in days]
        if not any(any(v) for v in ser) and c not in (td or {}): continue
        def streak(i):
            n, sgn = 0, 0
            for v in reversed(ser):
                s = (v[i] > 0) - (v[i] < 0)
                if s == 0 or (sgn and s != sgn): break
                sgn = s; n += 1
            return n * sgn
        s5 = [sum(v[i] for v in ser[-5:]) for i in range(4)]; s20 = [sum(v[i] for v in ser) for i in range(4)]
        big = [h[1].get(c) for h in tdh if h[1].get(c)]
        ms = [r.get(c) for _, r in mg if r.get(c)]
        m_now = ms[-1][0] if ms else None; m_0 = ms[0][0] if ms else None; m_y = ms[-2][0] if len(ms) >= 2 else None
        stocks[c] = dict(n=(F.get(c) or {}).get("name", ""), fS=streak(0), tS=streak(1), f5=s5[0], t5=s5[1], d5=s5[2], a5=s5[3], f20=s20[0], t20=s20[1], a20=s20[3],
                         mg=m_now, mgD=(m_now - m_y) if m_y is not None else None, mg20=(m_now - m_0) if m_0 is not None else None,
                         mg20p=round((m_now / m_0 - 1) * 100, 1) if m_0 else None, sh=ms[-1][1] if ms else None, ssr=round(ms[-1][1] / ms[-1][0] * 100, 1) if ms and ms[-1][0] else None,
                         big=big[-1][0] if big else None, bigW=round(big[-1][0] - big[-2][0], 2) if len(big) >= 2 else None, b400=big[-1][1] if big else None, hold=big[-1][2] if big else None)
    out = dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), days=[f"{x[0]:%Y-%m-%d}" for x in days], tdcc=day, weeks=[h[0] for h in tdh], stocks=stocks,
               note="法人買賣超單位為張;大戶＝集保持股 1,000 張以上")
    fh.save(os.path.join(DATA, "chips.json"), out)
    # 個股頁用的明細(近 20 日 + 近 26 週)
    det = {c: dict(inst=[[x[0].strftime("%m-%d")] + x[1].get(c, [0, 0, 0, 0]) for x in days], tdcc=[[h[0]] + h[1][c] for h in tdh if c in h[1]],
                   mg=[[dd.strftime("%m-%d")] + r[c] for dd, r in mg if c in r]) for c in stocks}
    fh.save(os.path.join(RAW, "detail.json"), det)
    # 熱力圖
    q = quotes(); items = []
    import shares; FIX = shares.par_fix(F)
    for c, f in F.items():
        t = f.get("ttm") or {}; cap = t.get("cap")
        if not cap: continue
        if c in q: cl, ch, vol = q[c]
        else:                                                   # 今天沒成交(官網收盤價是 --):沿用上次股價,漲跌 0
            try: lp = f.get("px") or json.load(open(os.path.join(DATA, "stk", c + ".json"))).get("px")
            except Exception: lp = None
            if not lp: continue
            cl, ch, vol = lp, 0, 0
        mcap = cl * (FIX.get(c) or cap * 100) / 1e8     # 億元(非 10 元面額用實際股數)
        items.append([c, f.get("name"), f.get("ind") or "其他", round(mcap, 1), ch, cl, vol])
    items.sort(key=lambda x: -x[3])
    try:                                                       # 熱力圖日期＝行情日期(法人個股資料 16 點後才公布,不能拿它當日期)
        import quotes as QM; r0 = str((QM.twse_all() or [{}])[0].get("Date") or "")
        qd = f"{int(r0[:3]) + 1911}-{r0[3:5]}-{r0[5:7]}" if len(r0) == 7 else None
    except Exception: qd = None
    fh.save(os.path.join(DATA, "heatmap.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), date=qd or (out["days"][-1] if out["days"] else None), items=items))
    print(f"chips.json:{len(days)} 個交易日、{len(stocks)} 檔;集保 {len(tdh)} 週;heatmap {len(items)} 檔")

if __name__ == "__main__":
    main()
