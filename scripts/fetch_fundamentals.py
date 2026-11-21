"""巴菲特選股資料:上市櫃公司 10 年財報 + 歷年年底股價 + 目前股價
來源:
  公開資訊觀測站 財報彙總表(全部公司一次抓)
    ajax_t163sb04 綜合損益表   ajax_t163sb05 資產負債表   ajax_t163sb20 現金流量表
    TYPEK=sii 上市 / otc 上櫃;year=民國年;season=04 為全年(損益與現金流是累計數)
  證交所 MI_INDEX / 櫃買 afterTrading/otc   每年最後交易日收盤價(算歷年本益比)
  證交所 STOCK_DAY_ALL / 櫃買 daily_close_quotes   目前股價
  FinMind TaiwanStockInfo   公司產業別
輸出: data/fund/raw/*.json(每期原始解析,已抓過就跳過) -> data/fund/fundamentals.json
用法: python3 scripts/fetch_fundamentals.py [--years 10] [--refresh-latest]
"""
import json, os, re, sys, time, html, datetime as dt, urllib.request, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh

DATA = fh.DATA
FD = os.path.join(DATA, "fund"); RAW = os.path.join(FD, "raw")
os.makedirs(RAW, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}
TODAY = dt.date.today()
YEARS = int(sys.argv[sys.argv.index("--years") + 1]) if "--years" in sys.argv else 10
REFRESH = "--refresh-latest" in sys.argv

# ---------- 公開資訊觀測站 ----------
def mops(kind, typek, roc_year, season):
    body = urllib.parse.urlencode(dict(encodeURIComponent=1, step=1, firstin=1, off=1, isQuery="Y", TYPEK=typek, year=roc_year, season=f"{season:02d}")).encode()
    for i in range(5):
        try:
            req = urllib.request.Request(f"https://mopsov.twse.com.tw/mops/web/ajax_{kind}", data=body, headers=UA)
            s = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"   連線失敗({e}),{20 * (i + 1)} 秒後重試"); time.sleep(20 * (i + 1)); continue
        if "查詢過於頻繁" in s or "Overrun" in s or "too many" in s.lower():
            print("   查詢太頻繁,等 60 秒"); time.sleep(60); continue
        return s
    raise RuntimeError(f"{kind} {typek} {roc_year}Q{season} 抓不到")

def num(x):
    x = html.unescape(x).replace(",", "").strip()
    if x in ("", "--", "-", "N/A"): return None
    try: return float(x)
    except ValueError: return None

def parse(s):
    """回傳 {公司代號: {欄位: 數值, '_fmt': 表格格式, '_name': 名稱}}"""
    out = {}
    for t in re.findall(r"<table[^>]*class=['\"]hasBorder['\"].*?</table>", s, re.S):
        hdr = [re.sub(r"<[^>]+>|\s", "", h) for h in re.findall(r"<th[^>]*>(.*?)</th>", t, re.S)]
        if not hdr or hdr[0] != "公司代號": continue
        fmt = "bank" if "利息淨收益" in hdr else "ins" if any("保險" in h for h in hdr) else "sec" if "收益" in hdr and "營業收入" not in hdr else "gen"
        for r in re.findall(r"<tr class=['\"](?:even|odd)['\"]>(.*?)</tr>", t, re.S):
            td = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
            if len(td) < 3: continue
            rec = {h: num(v) for h, v in zip(hdr[2:], td[2:])}
            rec["_fmt"] = fmt; rec["_name"] = html.unescape(td[1])
            out[td[0]] = rec
    return out

def pick(rec, *names):
    for n in names:
        if rec.get(n) is not None: return rec[n]
    return None

# 只留選股需要的欄位(單位:仟元;EPS 元)
def slim_is(r):
    rev = pick(r, "營業收入", "收益", "收益合計", "營業收入合計")
    if rev is None and r.get("利息淨收益") is not None: rev = (r.get("利息淨收益") or 0) + (r.get("利息以外淨損益") or 0)
    return dict(rev=rev, gp=pick(r, "營業毛利（毛損）淨額", "營業毛利（毛損）"), op=pick(r, "營業利益（損失）"),
                ni=pick(r, "本期淨利（淨損）", "本期稅後淨利（淨損）"), niP=pick(r, "淨利（淨損）歸屬於母公司業主", "淨利（損）歸屬於母公司業主"),
                eps=pick(r, "基本每股盈餘（元）", "基本每股盈餘"),
                pt=pick(r, "稅前淨利（淨損）", "繼續營業單位稅前淨利（淨損）", "繼續營業單位稅前損益", "稅前損益", "繼續營業單位稅前純益（純損）"),
                fmt=r["_fmt"], name=r["_name"])
def slim_bs(r):
    return dict(ca=pick(r, "流動資產"), cl=pick(r, "流動負債"), ta=pick(r, "資產總計", "資產總額", "資產合計"), tl=pick(r, "負債總計", "負債總額", "負債合計"), ncl=pick(r, "非流動負債"),
                eq=pick(r, "權益總計", "權益總額", "權益合計"), eqP=pick(r, "歸屬於母公司業主之權益合計", "歸屬於母公司業主之權益"),
                cap=pick(r, "股本"), bvps=pick(r, "每股參考淨值"))
def slim_cf(r):
    return dict(cfo=pick(r, "營業活動之淨現金流入（流出）"), cfi=pick(r, "投資活動之淨現金流入（流出）"), cff=pick(r, "籌資活動之淨現金流入（流出）"))
KINDS = [("is", "t163sb04", slim_is), ("bs", "t163sb05", slim_bs), ("cf", "t163sb20", slim_cf)]

def periods():
    """最近 YEARS 個完整年度(Q4) + 今年最新一季累計 + 去年同季(算近四季)"""
    last_full = TODAY.year - 1 if TODAY >= dt.date(TODAY.year, 4, 1) else TODAY.year - 2   # 年報 3/31 前公布
    ps = [(y, 4) for y in range(last_full - YEARS + 1, last_full + 1)]
    q = 3 if TODAY >= dt.date(TODAY.year, 11, 15) else 2 if TODAY >= dt.date(TODAY.year, 8, 15) else 1 if TODAY >= dt.date(TODAY.year, 5, 16) else 0
    if q and last_full == TODAY.year - 1: ps += [(TODAY.year, q), (TODAY.year - 1, q)]
    return ps, (TODAY.year, q) if q else None

def fetch_mops():
    ps, latest = periods()
    for y, s in ps:
        for typek in ("sii", "otc"):
            for k, ep, slim in KINDS:
                p = os.path.join(RAW, f"{k}_{y}Q{s}_{typek}.json")
                if os.path.exists(p) and not (REFRESH and (y, s) == latest):
                    if k != "is": continue
                    old = json.load(open(p))
                    if any("pt" in v for v in list(old.values())[:20]): continue      # 已含稅前淨利
                    print(f"   {k} {y}Q{s} {typek} 補抓稅前淨利")
                t0 = time.time()
                try: rows = parse(mops(ep, typek, y - 1911, s))
                except Exception as e: print(f"   {k} {y}Q{s} {typek} 失敗,下次再補:", e); continue
                if not rows: print(f"   {k} {y}Q{s} {typek} 沒有資料(可能尚未公布)"); continue
                fh.save(p, {c: slim(r) for c, r in rows.items()})
                print(f"{k} {y}Q{s} {typek}: {len(rows)} 家 ({time.time() - t0:.0f}s)", flush=True)
                time.sleep(6)                          # 公開資訊觀測站限制頻率
    return ps, latest

# ---------- 股價 ----------
def get_json(url, timeout=60):
    for i in range(3):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read())
        except Exception as e:
            if i == 2: raise
            time.sleep(5)

def year_end_prices(y):
    return prices_on(dt.date(y, 12, 31), f"px_{y}", cache=True)

def prices_on(day, tag, cache=True):
    """某日(或之前最近的交易日)全部上市櫃收盤價"""
    p = os.path.join(RAW, f"{tag}.json")
    if cache and os.path.exists(p): return json.load(open(p))
    out = {}
    try: return _prices_on(day, tag, p, out)
    except Exception as e:                             # 抓不到就沿用舊快取,不讓整個選股中斷
        print(f"  {tag} 股價失敗,沿用舊資料:", e)
        return json.load(open(p)) if os.path.exists(p) else {}

def _prices_on(day, tag, p, out):
    for back in range(0, 12):
        d = day - dt.timedelta(days=back)
        if d.weekday() >= 5: continue
        tw = get_json(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d:%Y%m%d}&type=ALLBUT0999&response=json")
        tabs = [t for t in tw.get("tables", []) if len(t.get("data", [])) > 300] if tw.get("stat") == "OK" else []
        if not tabs: time.sleep(2); continue
        f = tabs[0]["fields"]; ci = f.index("收盤價")
        for r in tabs[0]["data"]:
            v = num(r[ci]);
            if v: out[r[0]] = v
        time.sleep(3)
        tp = get_json(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date={d:%Y/%m/%d}&type=EW&response=json")
        for t in tp.get("tables", []):
            ci = [k for k, x in enumerate(t.get("fields", [])) if x.strip() == "收盤"]
            for r in t.get("data", []) if ci else []:
                v = num(r[ci[0]])
                if v: out[r[0]] = v
        out["_date"] = d.isoformat(); break
    if len(out) < 300: raise RuntimeError(f"只抓到 {len(out)} 檔")
    fh.save(p, out); print(f"{tag} 股價 {out.get('_date')}: {len(out) - 1} 檔"); time.sleep(3)
    return out

def monthly_revenue(n=3):
    """最近 n 個已公布月份的月營收(公開資訊觀測站彙總表):{代號:[[yyyymm, 當月, 去年當月, 當月累計, 去年累計], ...]}"""
    out = {}; got = 0
    m = TODAY.replace(day=1)
    for _ in range(n + 3):
        m = (m - dt.timedelta(days=1)).replace(day=1)
        if got >= n: break
        p = os.path.join(RAW, f"rev_{m:%Y%m}.json")
        if os.path.exists(p) and m < (TODAY.replace(day=1) - dt.timedelta(days=40)).replace(day=1): rows = json.load(open(p))
        else:
            rows = {}; bad = False
            for mk in ("sii", "otc"):
                b = None
                for k in range(3):
                    try: b = urllib.request.urlopen(urllib.request.Request(f"https://mopsov.twse.com.tw/nas/t21/{mk}/t21sc03_{m.year - 1911}_{m.month}_0.html", headers=UA), timeout=90).read(); break
                    except Exception as e: print("  月營收", m, mk, "失敗", e); time.sleep(8)
                if b is None: bad = True; continue
                t = b.decode("cp950", errors="ignore")
                for r in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
                    td = [re.sub(r"<[^>]+>|&nbsp;", "", x).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S | re.I)]   # 有些格子寫成 <Td
                    if len(td) >= 9 and re.match(r"^\d{4}$", td[0]):
                        rows[td[0]] = [num(td[2]), num(td[4]), num(td[7]), num(td[8])]
                time.sleep(4)
            if len(rows) < 500: print(f"  {m:%Y-%m} 月營收尚未齊全({len(rows)} 家),略過"); continue
            if not bad: fh.save(p, rows)                      # 有市場抓失敗就不存快取,下次重抓
        got += 1; print(f"{m:%Y-%m} 月營收 {len(rows)} 家")
        for c, v in rows.items(): out.setdefault(c, []).append([f"{m:%Y%m}"] + v)
    return out

VOL = {}
def current_prices():
    q, day = {}, None
    try:
        for x in get_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", 90):
            v = num(x.get("ClosingPrice", ""));
            if v: q[x["Code"]] = v
            tv = num(x.get("TradeVolume", "")); day = day or x.get("Date")
            if tv is not None: VOL[x["Code"]] = round(tv / 1000)
    except Exception as e: print("證交所目前股價失敗:", e)
    try:
        for x in get_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes", 180):
            v = num(x.get("Close", ""))
            if v: q[x["SecuritiesCompanyCode"]] = v
            tv = num(x.get("TradingShares", ""))
            if tv is not None: VOL[x["SecuritiesCompanyCode"]] = round(tv / 1000)
    except Exception as e: print("櫃買目前股價失敗:", e)
    # 五日均量:保留最近 5 個交易日的成交量
    hp = os.path.join(RAW, "vol_hist.json"); hist = json.load(open(hp)) if os.path.exists(hp) else {}
    if VOL and day:
        hist[str(day)] = VOL; hist = {k: hist[k] for k in sorted(hist)[-5:]}; fh.save(hp, hist)
    for c in list(VOL):
        vs = [h[c] for h in hist.values() if c in h]; VOL[c] = round(sum(vs) / len(vs)) if vs else VOL[c]
    print("目前股價", len(q), "檔;五日均量用", len(hist), "天"); return q

def industries():
    try:
        rows = fh.finmind("TaiwanStockInfo", "", "")
        out = {}
        for r in rows:                                 # 同一檔可能有多個分類,優先用較具體的(如「半導體業」而非「電子工業」)
            if r["type"] not in ("twse", "tpex"): continue
            cat = r["industry_category"]; old = out.get(r["stock_id"])
            if old and cat in ("電子工業", "其他電子類", "其他", "創新板股票", "存託憑證"): continue
            out[r["stock_id"]] = dict(ind=cat, mkt="上市" if r["type"] == "twse" else "上櫃")
        return out
    except Exception as e:
        print("產業別失敗:", e); return {}

# ---------- 合併 ----------
def build(ps, latest):
    years = sorted({y for y, s in ps if s == 4})
    comp = {}
    def load(k, y, s):
        out = {}
        for typek in ("sii", "otc"):
            p = os.path.join(RAW, f"{k}_{y}Q{s}_{typek}.json")
            if os.path.exists(p): out.update(json.load(open(p)))
        return out
    for y in years:
        I, B, C = load("is", y, 4), load("bs", y, 4), load("cf", y, 4)
        for c, r in I.items():
            d = comp.setdefault(c, dict(name=r["name"], fmt=r["fmt"], y={}))
            d["name"], d["fmt"] = r["name"], r["fmt"]
            d["y"][y] = {**{k: r.get(k) for k in ("rev", "gp", "op", "ni", "niP", "eps", "pt")}, **(B.get(c) or {}), **(C.get(c) or {})}
    if latest:                                         # 近四季 = 去年全年 + 今年累計 - 去年同期累計
        (yy, q) = latest
        Icur, Iprev, Ccur, Cprev, Bcur = load("is", yy, q), load("is", yy - 1, q), load("cf", yy, q), load("cf", yy - 1, q), load("bs", yy, q)
        for c, d in comp.items():
            full = d["y"].get(yy - 1)
            if not full: continue
            if c not in Icur or c not in Iprev:              # 最新一季還沒公布(例如金控較晚):先用上一個完整年度
                d["ttm"] = dict(full); d["ttmLabel"] = f"{yy - 1} 全年"; continue
            ttm = {}
            for k in ("rev", "gp", "op", "ni", "niP", "eps", "pt"):
                a, b, f = Icur[c].get(k), Iprev[c].get(k), full.get(k)
                ttm[k] = None if None in (a, b, f) else round(f + a - b, 2)
            for k in ("cfo", "cfi"):
                a, b, f = (Ccur.get(c) or {}).get(k), (Cprev.get(c) or {}).get(k), full.get(k)
                ttm[k] = None if None in (a, b, f) else f + a - b
            ttm.update({k: v for k, v in (Bcur.get(c) or {}).items()})
            d["ttm"] = ttm; d["ttmLabel"] = f"{yy}Q{q} 近四季"
    px_year = {y: year_end_prices(y) for y in years}
    now = current_prices(); ind = industries()
    p1m = prices_on(TODAY - dt.timedelta(days=30), "px_1m", cache=False)       # 價格動能:1 個月前、1 年前
    p12m = prices_on(TODAY - dt.timedelta(days=365), "px_12m", cache=False)
    rev = monthly_revenue(24)                          # 近 2 年月營收(個股頁趨勢、營收創新高)
    for c, d in comp.items():
        d["px"] = now.get(c); d["pxY"] = {y: px_year[y].get(c) for y in years if px_year[y].get(c)}
        d["px1m"], d["px12m"] = p1m.get(c), p12m.get(c); d["vol5"] = VOL.get(c)
        if c in rev: d["rev"] = sorted(rev[c], reverse=True)
        d.update(ind.get(c, {}))
    out = dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), years=years, latest=f"{latest[0]}Q{latest[1]}" if latest else None,
               unit="財報金額單位:仟元;EPS 元", companies=comp)
    fh.save(os.path.join(FD, "fundamentals.json"), out)
    print(f"fundamentals.json: {len(comp)} 家公司,{years[0]}~{years[-1]}" + (f" + {out['latest']}" if latest else ""))

if __name__ == "__main__":
    ps, latest = fetch_mops()
    build(ps, latest)
