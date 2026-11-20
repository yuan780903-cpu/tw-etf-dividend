"""個股公司資料:產品與商業模式 -> data/profiles.json
  Yahoo 股市 公司基本資料:主要經營業務、產業、成立、董事長、網站、集團、毛利率、營益率
  MoneyDJ 基本資料:營收比重(各產品占營收 %)
用法: python3 scripts/fetch_profiles.py [--max 200]   (每次更新最舊的 N 家;預設全部)
"""
import json, os, re, sys, html, time, datetime as dt, urllib.request, concurrent.futures as cf
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; OUT = os.path.join(DATA, "profiles.json"); RAW = os.path.join(DATA, "breadth", "raw")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
MAXN = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 0
TODAY = dt.date.today().isoformat()

def get(url, enc="utf-8"):
    for i in range(3):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read().decode(enc, errors="ignore")
        except Exception as e:
            if i == 2: return ""
            time.sleep(3 * (i + 1))

def yahoo(code):
    for suf in (".TW", ".TWO"):
        s = get(f"https://tw.stock.yahoo.com/quote/{code}{suf}/profile")
        pairs = {k: html.unescape(re.sub(r"<[^>]+>", "", v)).strip() for k, v in re.findall(r'<span>([^<]{2,14})</span></span><div class="Py\(8px\)[^"]*">(.*?)</div>', s, re.S)}
        if pairs.get("公司名稱"): return pairs
    return {}

def moneydj(code):
    s = get(f"https://concords.moneydj.com/z/zc/zca/zca_{code}.djhtm", "big5")
    cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", c))).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", s, re.S)]
    out = {}
    for i, c in enumerate(cells[:-1]):
        if c == "營收比重": out["mix"] = cells[i + 1]
    return out

def parse_mix(t):
    if not t: return [], None
    yr = re.search(r"\((\d{4})年\)", t)
    items = []
    for name, pct in re.findall(r"([^、%]+?)\s*(-?\d+(?:\.\d+)?)%", t.split("(")[0] if "(" in t[-10:] else t):
        name = name.strip("、 ").strip()
        if name: items.append([name, float(pct)])
    items.sort(key=lambda x: -x[1])
    return items[:12], yr.group(1) if yr else None

def summary(p):
    name, ind, biz, mix = p.get("name", ""), p.get("ind", ""), p.get("biz", ""), p.get("mix", [])
    first = re.split(r"[。；;]", biz.replace("\n", ""))[0][:90] if biz else ""
    s = f"{name}屬於「{ind}」產業。" if ind else ""
    if first: s += f"主要業務：{first}。"
    real = [m for m in mix if not re.match(r"^其他", m[0])]
    if real:
        top = real[0]; t3 = sum(m[1] for m in real[:3])
        s += f"最主要靠「{top[0]}」賺錢，約占營收 {top[1]:.0f}%"
        s += f"；前三大產品合計 {t3:.0f}%，{'營收很集中，主力產品的景氣好壞影響很大' if top[1] >= 50 else '營收來源算分散' if t3 < 60 else '營收集中在少數產品'}。" if 1 < len(real) and t3 <= 100.5 else "。"
    gm = p.get("gm")
    if gm is not None and not re.search(r"金融|銀行|保險|證券", ind):
        s += f"毛利率約 {gm:.0f}%，" + ("產品有定價能力、附加價值高。" if gm >= 40 else "屬於中等毛利的生意。" if gm >= 20 else "毛利偏低，靠量取勝或屬於代工、通路型生意。")
    return s

def fetch_one(code):
    y = yahoo(code); time.sleep(.4); m = moneydj(code)
    num = lambda v: float(v.replace("%", "").replace(",", "")) if v and re.match(r"^-?[\d,.]+%?$", v) else None
    mix, yr = parse_mix(m.get("mix"))
    p = dict(name=y.get("公司名稱", ""), ind=re.sub(r"^櫃", "", y.get("產業類別", "")), biz=re.sub(r"\s+", "", y.get("主要經營業務", "")), mix=mix, mixYear=yr,
             gm=num(y.get("營業毛利率")), om=num(y.get("營業利益率")), est=y.get("成立時間"), chair=y.get("董事長"), web=y.get("公司網站"),
             group=y.get("所屬集團"), mkt=y.get("市場別"), cap=y.get("市值 (百萬)"), upd=TODAY)
    p["say"] = summary(p)
    return code, p

def main():
    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    last = sorted(f for f in os.listdir(RAW) if f.endswith(".json"))[-1]
    codes = sorted(json.load(open(os.path.join(RAW, last)))["c"])
    codes.sort(key=lambda c: old.get(c, {}).get("upd", ""))   # 最舊(或沒有)的先抓
    todo = [c for c in codes if old.get(c, {}).get("upd") != TODAY]
    if MAXN: todo = todo[:MAXN]
    print(f"共 {len(codes)} 家,本次更新 {len(todo)} 家", flush=True)
    n = 0
    with cf.ThreadPoolExecutor(4) as ex:
        for code, p in ex.map(fetch_one, todo):
            n += 1
            if p["name"] or p["mix"]: old[code] = p
            if n % 100 == 0:
                fh.save(OUT, old); print(f"  {n}/{len(todo)}", flush=True)
    fh.save(OUT, old)
    print(f"profiles.json: {len(old)} 家;有營收比重 {sum(1 for p in old.values() if p.get('mix'))} 家")

if __name__ == "__main__":
    main()
