"""市場廣度(恐慌度用):全部上市櫃普通股每日收盤 -> data/breadth.json
  跌停家數比例(5 日平均)、創 52 週新低比例(5 日平均)、站上 200 日線比例
來源:證交所 MI_INDEX(每日收盤行情 + 漲跌證券數合計的「跌停」家數)、櫃買 afterTrading/otc(漲跌幅 ≤ -9.5% 視為跌停)
每日原始資料快取在 data/breadth/raw/YYYY-MM-DD.json(不進 git;雲端用 Actions 快取保存近 270 個交易日)
用法: python3 scripts/fetch_breadth.py [--since 2020-09-01] [--keep 270]
"""
import json, os, re, sys, time, datetime as dt, urllib.request, collections, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh

DATA = fh.DATA; RAW = os.path.join(DATA, "breadth", "raw"); os.makedirs(RAW, exist_ok=True)
OUT = os.path.join(DATA, "breadth.json")
UA = {"User-Agent": "Mozilla/5.0"}
arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
SINCE = arg("--since", (dt.date.today() - dt.timedelta(days=420)).isoformat())
UNTIL = arg("--until", "9999-12-31")
KEEP = int(arg("--keep", "0"))
MAXN = int(arg("--max", "0"))                          # 每次最多補幾天(雲端第一次沒快取時分幾次補完)
STOCK = re.compile(r"^[1-9]\d{3}$")                    # 普通股(4 碼、非 0 開頭;排除 ETF/權證)

def num(x):
    x = re.sub(r"<[^>]+>", "", str(x)).replace(",", "").strip()
    try: return float(x)
    except ValueError: return None

def get(url):
    for i in range(4):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read())
        except Exception as e:
            if i == 3: raise
            time.sleep(8 * (i + 1))

def fetch_day(d):
    out = {"c": {}, "dnT": None, "nT": None, "dnO": 0, "nO": 0}
    tw = get(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d:%Y%m%d}&type=ALLBUT0999&response=json")
    if tw.get("stat") != "OK": return None
    for t in tw.get("tables", []):
        f = t.get("fields") or []
        if "證券代號" in f and "收盤價" in f:
            ci, si, di = f.index("收盤價"), f.index("漲跌(+/-)"), f.index("漲跌價差")
            for r in t.get("data", []):
                if STOCK.match(r[0]) and num(r[ci]): out["c"][r[0]] = num(r[ci])
        if (t.get("title") or "").startswith("漲跌證券數合計"):
            k = f.index("股票") if "股票" in f else 2; n = 0
            for r in t.get("data", []):
                m = re.match(r"([\d,]+)(?:\((\d+)\))?", str(r[k]))
                if not m: continue
                n += int(m.group(1).replace(",", ""))
                if "跌停" in r[0]: out["dnT"] = int(m.group(2) or 0)
            out["nT"] = n
    if not out["c"]: return None
    time.sleep(1.5)
    tp = get(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date={d:%Y/%m/%d}&type=EW&response=json")
    for t in tp.get("tables", []):
        f = [x.strip() for x in t.get("fields") or []]
        if "代號" not in f or "收盤" not in f: continue
        ci, chi = f.index("收盤"), f.index("漲跌")
        for r in t.get("data", []):
            if not STOCK.match(r[0]): continue
            c, ch = num(r[ci]), num(r[chi])
            if not c: continue
            out["c"][r[0]] = c; out["nO"] += 1
            if ch is not None and c - ch > 0 and ch / (c - ch) <= -0.095: out["dnO"] += 1
    return out

def trading_days():
    rows = fh.finmind("TaiwanStockPrice", "TAIEX", SINCE)
    days = [r["date"] for r in rows]
    tx = json.load(open(os.path.join(DATA, "taiex.json")))       # 補上 FinMind 還沒有的最新一天
    days += [r[0] for r in tx if r[0] > (days[-1] if days else "")]
    return sorted(d for d in set(days) if d <= UNTIL)

def backfill(days):
    have = {f[:10] for f in os.listdir(RAW)}
    todo = [d for d in days if d not in have]
    if MAXN: todo = todo[-MAXN:]                       # 先補最近的
    print(f"交易日 {len(days)} 天,需下載 {len(todo)} 天", flush=True)
    for k, d in enumerate(todo, 1):
        try: r = fetch_day(dt.date.fromisoformat(d))
        except Exception as e: print(f"  {d} 失敗:{e}", flush=True); continue
        if r: fh.save(os.path.join(RAW, d + ".json"), r)
        if k % 25 == 0 or k == len(todo): print(f"  {k}/{len(todo)} {d} {len(r['c']) if r else 0} 檔", flush=True)
        time.sleep(1.5)

def compute():
    files = sorted(f for f in os.listdir(RAW) if f.endswith(".json"))
    hist = collections.defaultdict(lambda: collections.deque(maxlen=252))
    old = {r[0]: r for r in (json.load(open(OUT))["rows"] if os.path.exists(OUT) else [])}
    ld, lows, out = collections.deque(maxlen=5), collections.deque(maxlen=5), {}
    for i, f in enumerate(files):
        d = f[:10]; day = json.load(open(os.path.join(RAW, f)))
        n_low = n_elig = n_up = n_200 = 0
        for code, c in day["c"].items():
            h = hist[code]
            if len(h) >= 200:
                n_elig += 1
                if c <= min(h): n_low += 1
                ma = sum(list(h)[-199:] + [c]) / 200
                n_200 += 1; n_up += c > ma
            h.append(c)
        n = (day.get("nT") or 0) + (day.get("nO") or 0)
        ld.append(((day.get("dnT") or 0) + (day.get("dnO") or 0)) / n * 100 if n else None)
        lows.append(n_low / n_elig * 100 if n_elig else None)
        if i >= 252 and n_elig > 500:                  # 前 252 天只用來暖機
            m = lambda q: round(st.mean([x for x in q if x is not None]), 2) if any(x is not None for x in q) else None
            out[d] = [d, m(ld), m(lows), round(n_up / n_200 * 100, 1) if n_200 else None]
    old.update(out)
    rows = sorted(old.values())
    fh.save(OUT, dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), cols=["d", "ld5", "low5", "a200"], rows=rows,
                      note="ld5=跌停家數比例5日平均%;low5=創52週新低比例5日平均%;a200=站上200日線比例%(上市櫃普通股)"))
    print(f"breadth.json: {len(rows)} 天" + (f",最新 {rows[-1]}" if rows else ""))

if __name__ == "__main__":
    backfill(trading_days())
    if KEEP:
        fs = sorted(os.listdir(RAW))
        for f in fs[:-KEEP]: os.remove(os.path.join(RAW, f))
    if "--no-compute" not in sys.argv: compute()
