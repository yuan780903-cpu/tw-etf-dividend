"""大盤儀表板資料:近 5 年每日彙整 -> data/market.json
來源(全部免費、官方或公開):
  證交所 MI_MARGN_TREND      上市融資餘額/融資金額/融資擔保市值/融券   (2021~,每次最多 60 天)
  證交所 BFIJ3U_TREND        整戶擔保維持率/追繳/處分 (臺股儀表板,2026-08-03 起才有官方數字)
  FinMind TotalInstitutional  三大法人買賣超(上市)
  FinMind FuturesInstitutional 三大法人台指期(TX)未平倉
  期交所 VIX log2data         台指 VIX (官網只留近幾個月,之後每天累積)
  FRED VIXCLS                 美股 VIX (5 年)
增量:原始資料快取在 data/market/raw_*.json,每次只補最近幾天;--full 重抓全部。
用法: python3 scripts/fetch_market.py [--full]
"""
import json, os, sys, time, datetime as dt, urllib.request, csv, io
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh

DATA = fh.DATA
MD = os.path.join(DATA, "market"); os.makedirs(MD, exist_ok=True)
TODAY = dt.date.today()
START = dt.date(TODAY.year - 5, TODAY.month, 1)
FULL = "--full" in sys.argv
UA = {"User-Agent": "Mozilla/5.0"}

def get(url, timeout=60, tries=3, raw=False):
    for i in range(tries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
            return b if raw else json.loads(b)
        except Exception as e:
            if i == tries - 1: raise
            print("  重試:", e); time.sleep(3 * (i + 1))

def load(name, default):
    p = os.path.join(MD, f"raw_{name}.json")
    try: return json.load(open(p))
    except Exception: return default

def save(name, obj): fh.save(os.path.join(MD, f"raw_{name}.json"), obj)

def iso(d8): return f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}"

# ---------- 證交所:往回分頁抓(每頁 60 天) ----------
def twse_paged(api, since, have):
    """從今天往回抓到 since;have = 已有資料 dict(date->row)。增量時抓到已有日期就停。"""
    end = TODAY; n = 0
    while end >= since:
        d = get(f"https://www.twse.com.tw/rwd/zh/marginTrading/{api}?date={end:%Y%m%d}&days=60&response=json")
        rows = d.get("data") or [] if d.get("stat") == "OK" else []
        if not rows: break
        new = 0
        for r in rows:
            k = iso(r["date"]); new += k not in have; have[k] = r
        n += len(rows)
        first = dt.date.fromisoformat(iso(rows[0]["date"]))
        if not FULL and new < len(rows): break          # 已接上舊資料
        end = first - dt.timedelta(days=1)
        time.sleep(2.5)                                 # 證交所有頻率限制,慢慢抓
    return n

def fetch_margin():
    have = {} if FULL else load("margin", {})
    n = twse_paged("MI_MARGN_TREND", START, have); save("margin", have)
    print(f"融資(上市) 抓 {n} 筆,共 {len(have)} 天")
    return have

def fetch_keep():
    have = {} if FULL else load("keep", {})
    n = twse_paged("BFIJ3U_TREND", dt.date(2026, 8, 3), have); save("keep", have)
    print(f"整戶維持率/追繳 抓 {n} 筆,共 {len(have)} 天")
    return have

# ---------- FinMind ----------
def fm_since(have, back=15):
    if FULL or not have: return START.isoformat()
    return (dt.date.fromisoformat(max(have)) - dt.timedelta(days=back)).isoformat()

def fetch_inst():
    have = {} if FULL else load("inst", {})
    for r in fh.finmind("TaiwanStockTotalInstitutionalInvestors", "", fm_since(have)):
        have.setdefault(r["date"], {})[r["name"]] = round((r["buy"] - r["sell"]) / 1e8, 2)   # 億元
    save("inst", have); print(f"三大法人 共 {len(have)} 天"); return have

def fetch_fut():
    have = {} if FULL else load("fut", {})
    for r in fh.finmind("TaiwanFuturesInstitutionalInvestors", "TX", fm_since(have)):
        have.setdefault(r["date"], {})[r["institutional_investors"]] = r["long_open_interest_balance_volume"] - r["short_open_interest_balance_volume"]
    save("fut", have); print(f"台指期法人未平倉 共 {len(have)} 天"); return have

# ---------- VIX ----------
def fetch_vix_tw():
    have = load("vixtw", {})
    m = TODAY.replace(day=1); months = []
    for _ in range(6 if (FULL or not have) else 2):
        months.append(m); m = (m - dt.timedelta(days=1)).replace(day=1)
    for m in months:
        try: b = get(f"https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{m:%Y%m}new.txt", raw=True)
        except Exception as e: print("  台指VIX", m, "失敗", e); continue
        for line in b.decode("big5", errors="ignore").splitlines():
            p = line.split()
            if len(p) >= 3 and p[0].isdigit() and len(p[0]) == 8:
                try: have[iso(p[0])] = float(p[2])
                except ValueError: pass
    save("vixtw", have); print(f"台指VIX 共 {len(have)} 天"); return have

def fetch_vix_us():
    have = load("vixus", {})
    since = START if (FULL or not have) else dt.date.fromisoformat(max(have)) - dt.timedelta(days=10)
    try:                                               # 先用 Yahoo ^VIX,失敗再用 FRED
        r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range={'5y' if (FULL or not have) else '1mo'}&interval=1d", timeout=30)["chart"]["result"][0]
        off = r["meta"].get("gmtoffset", 0)
        for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]):
            if c: have[dt.datetime.fromtimestamp(t + off, dt.timezone.utc).date().isoformat()] = round(c, 2)
    except Exception as e:
        print("  美股VIX(Yahoo) 失敗,改用 FRED:", e)
        try:
            b = urllib.request.urlopen(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS&cosd={since}", timeout=30).read()
            for r in csv.DictReader(io.StringIO(b.decode())):
                try: have[r["observation_date"]] = float(r["VIXCLS"])
                except (ValueError, KeyError): pass
        except Exception as e2: print("  美股VIX 失敗", e2)
    save("vixus", have); print(f"美股VIX 共 {len(have)} 天"); return have

# ---------- 合併成每日一列 ----------
COLS = ["d", "tx", "txH", "txL", "txV",            # 加權指數 收/高/低/成交(億)
        "mShr", "mAmt", "mVal", "mKeep", "sShr",    # 融資餘額(張) 融資金額(億) 融資擔保市值(億) 估算融資維持率% 融券餘額(張)
        "keep", "below", "callN", "callAmt", "exeN", "exeAmt", "mAcc",   # 官方整戶維持率% 低於130%戶數 追繳戶數 追繳金額(億) 處分戶數 處分金額(億) 融資戶數
        "fi", "it", "dl", "tot",                    # 外資 投信 自營商 合計 買賣超(億)
        "ffi", "fit", "fdl",                        # 外資/投信/自營 台指期淨未平倉(口)
        "vixTw", "vixUs"]

def build(margin, keep, inst, fut, vtw, vus):
    tx = {r[0]: r for r in json.load(open(os.path.join(DATA, "taiex.json")))}
    days = sorted(d for d in tx if d >= START.isoformat())
    last_us = None; rows = []
    for d in days:
        t = tx[d]; m = margin.get(d) or {}; k = keep.get(d) or {}; i = inst.get(d) or {}; f = fut.get(d) or {}
        if d in vus: last_us = vus[d]                  # 美股與台股假日不同 -> 沿用前一個值
        mAmt = m.get("marginAmt"); mVal = m.get("marketValue")
        dealer = None
        if i: dealer = round(sum(v for n, v in i.items() if n.startswith("Dealer")), 2)
        rows.append([d, t[4], t[2], t[3], round(t[5] / 1e5, 1) if t[5] else None,
                     m.get("marginShr"), round(mAmt / 1e5, 1) if mAmt else None, round(mVal / 100, 1) if mVal else None,
                     round(mVal * 1e6 / (mAmt * 1e3) * 100, 2) if mAmt and mVal else None, m.get("shortShr"),
                     k.get("keepRate"), k.get("belowAccNum"), k.get("callAccNum"),
                     round(k["callAmt"] / 1e8, 2) if k.get("callAmt") is not None else None,
                     k.get("exeAccNum"), round(k["exeAmt"] / 1e8, 2) if k.get("exeAmt") is not None else None, k.get("marginAccNum"),
                     i.get("Foreign_Investor"), i.get("Investment_Trust"), dealer, i.get("total"),
                     f.get("外資"), f.get("投信"), f.get("自營商"),
                     vtw.get(d), last_us])
    out = dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), cols=COLS, rows=rows,
               note="融資相關為上市;估算融資維持率=融資擔保市值÷融資金額;整戶維持率/追繳為證交所官方(2026-08-03起)")
    fh.save(os.path.join(DATA, "market.json"), out)
    print(f"market.json: {len(rows)} 天,{rows[0][0]} ~ {rows[-1][0]}")

# ---------- 全球主要股市指數(Yahoo 日線) -> data/global.json ----------
GLOBAL = [("^GSPC","美國 標普500","美洲"), ("^IXIC","美國 那斯達克","美洲"), ("^DJI","美國 道瓊工業","美洲"), ("^SOX","美國 費城半導體","美洲"),
          ("^N225","日本 日經225","亞洲"), ("^KS11","韓國 KOSPI","亞洲"), ("^HSI","香港 恆生","亞洲"), ("000001.SS","中國 上證綜合","亞洲"),
          ("^BSESN","印度 SENSEX","亞洲"), ("^STI","新加坡 海峽時報","亞洲"), ("^GDAXI","德國 DAX","歐洲"), ("^FTSE","英國 富時100","歐洲")]

MACRO = [("TWD=X", "美元兌台幣", "匯率"), ("^TNX", "美國 10 年期公債殖利率", "利率"), ("CL=F", "西德州原油", "原物料")]

def fetch_global():
    old = (load("global", {}) or {})
    out = {}
    for sym, name, reg in GLOBAL + MACRO:
        rows = dict(old.get(sym, {}).get("rows", []))
        rng = "5y" if (FULL or not rows) else "1mo"
        try:
            r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?range={rng}&interval=1d")["chart"]["result"][0]
            off = r["meta"].get("gmtoffset", 0)
            for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]):
                if c: rows[dt.datetime.fromtimestamp(t + off, dt.timezone.utc).date().isoformat()] = round(c, 2)
            ccy = r["meta"].get("currency")
        except Exception as e:
            print(f"  {name} 失敗,沿用舊資料:", e); ccy = old.get(sym, {}).get("ccy")
        keep = sorted((d, v) for d, v in rows.items() if d >= START.isoformat())
        out[sym] = dict(name=name, region=reg, ccy=ccy, rows=keep)
        time.sleep(0.8)
    save("global", out)
    msyms = {m[0] for m in MACRO}
    fh.save(os.path.join(DATA, "global.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            idx={k: v for k, v in out.items() if k not in msyms}, macro={k: v for k, v in out.items() if k in msyms}))
    print("全球指數:", ", ".join(f"{v['name']} {len(v['rows'])}天" for v in out.values()))

def main():
    try: fetch_global()
    except Exception as e: print("全球指數失敗:", e)
    steps = [("margin", fetch_margin), ("keep", fetch_keep), ("inst", fetch_inst), ("fut", fetch_fut), ("vixtw", fetch_vix_tw), ("vixus", fetch_vix_us)]
    got = {}
    for name, fn in steps:                              # 單一來源失敗不影響其他,沿用舊快取
        try: got[name] = fn()
        except Exception as e: print(f"{name} 失敗,沿用舊資料:", e); got[name] = load(name, {})
    build(got["margin"], got["keep"], got["inst"], got["fut"], got["vixtw"], got["vixus"])

if __name__ == "__main__":
    main()
