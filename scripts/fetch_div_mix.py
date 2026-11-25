"""ETF 配息來源組成(股利所得/利息所得/收益平準金/已實現資本利得/其他所得 占比) -> data/div_mix.json
資料:證交所 ETF e添富「重大消息 → 收益分配」公告(2023/11 起投信公告配息時必須揭露組成占比)
  列表 https://www.twse.com.tw/zh/ETFortune/announcementList?type=distribution&max=10&offset=N(每頁 10 則,新到舊)
  內文 https://www.twse.com.tw/zh/ETFortune/announcement?company=..&date=..&seq=..&fund=..&type=distribution
用法:
  python fetch_div_mix.py              每天:看最新幾頁,碰到整頁都抓過就停
  python fetch_div_mix.py --backfill   第一次:一路抓到 2023/11 以前(約 240 頁列表＋2400 則內文,慢慢抓約 30 分鐘)
輸出 etfs[代號] = [[除息日, 每單位配息, 股利%, 利息%, 平準金%, 資本利得%, 其他%, 公告日, 公告序號], ...] 新到舊,每檔最多留 24 筆
"""
import json, os, re, sys, time, html as H, urllib.request, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net  # noqa: F401  證交所 cookie/307

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUT = os.path.join(DATA, "div_mix.json")
SEEN = os.path.join(DATA, "div_mix_seen.json")         # 抓過的公告清單(網頁不用,分開放讓 div_mix.json 小一點)
BASE = "https://www.twse.com.tw/zh/ETFortune/"
KEEP = 24
SINCE = "20231101"
LABELS = [("股利所得", 2), ("利息所得", 3), ("收益平準金", 4), ("已實現資本利得", 5), ("其他所得", 6)]


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r: return r.read().decode("utf-8", "ignore")
        except Exception as e:
            if i == tries - 1: print("  失敗", url[-80:], e); return None
            time.sleep(3 + i * 3)


def roc(y, m, d):
    y = int(y); y = y + 1911 if y < 1911 else y
    try: return dt.date(y, int(m), int(d)).isoformat()
    except ValueError: return None


def parse(page):
    """從公告內文取出:除息日、每單位配息、五項占比"""
    t = H.unescape(re.sub(r"<[^>]+>", " ", page)); t = re.sub(r"[ \t　]+", " ", t)
    i = t.find("說明")
    body = t[i:] if i >= 0 else t
    row = [None] * 7
    m = re.search(r"除息(?:交易)?日\s*[:：]?\s*(\d{2,4})\s*[/.年-]\s*(\d{1,2})\s*[/.月-]\s*(\d{1,2})", body)
    if m: row[0] = roc(*m.groups())
    m = (re.search(r"(?:配發|分配)金額[^0-9\n]{0,25}?(\d+(?:\.\d+)?)\s*元", body)
         or re.search(r"每受益權單位[^。\n]{0,40}?新臺幣\s*(\d+(?:\.\d+)?)\s*元", body))
    if m: row[1] = float(m.group(1))
    found = 0
    for lab, k in LABELS:
        pat = lab + r"(?:之)?(?:占比|比例|比率)?[^0-9%\n。]{0,30}?(-?\d+(?:\.\d+)?)\s*[%％]"
        if lab == "已實現資本利得":                     # 掩護性買權 ETF 會拆成「不含賣出選擇權權利金」＋「賣出選擇權權利金」兩行,要加總
            xs = [float(x) for x in re.findall(pat, body)]
            if xs: row[k] = min(100.0, sum(xs)); found += 1
            continue
        m = re.search(pat, body)
        if m: row[k] = float(m.group(1)); found += 1
    if found < 2: return None                    # 沒揭露組成(例如不分配、或 2023/11 以前)
    for k in range(2, 7):
        if row[k] is None: row[k] = 0.0
    if not 90 <= sum(row[2:7]) <= 110: return None   # 加起來不像 100%,寧可不要(格式沒解析對)
    return row


def fill_amount(fund, row):
    """公告沒寫到配息金額時,用網站自己的配息紀錄(同一個除息日)補"""
    if row[1] is not None or not row[0]: return row
    try:
        with open(os.path.join(DATA, "dividends", fund + ".json"), encoding="utf-8") as fh:
            for x in json.load(fh):
                if x.get("ex") == row[0] and x.get("cash"): row[1] = float(x["cash"]); break
    except Exception: pass
    return row


def list_page(off):
    h = get(f"{BASE}announcementList?type=distribution&max=10&offset={off}")
    if not h: return None
    out = []
    for c, d, s, f in re.findall(r"announcement\?company=(A\d+)&amp;date=(\d{8})&amp;seq=(\d+)&amp;fund=([0-9A-Z]+)&amp;type=", h):
        k = (c, d, s, f)
        if k not in out and f != "ZZZZ": out.append(k)
    return out


def main():
    back = "--backfill" in sys.argv
    old = {}
    try:
        with open(OUT, encoding="utf-8") as fh: old = json.load(fh)
    except Exception: pass
    E = old.get("etfs", {})
    seen = set(old.get("seen", []))               # 抓過的公告(含沒揭露組成的),避免每天重抓
    try:
        with open(SEEN, encoding="utf-8") as fh: seen |= set(json.load(fh))
    except Exception: pass
    new = 0; off = 0; stale = 0; maxp = 400 if back else 6
    for p in range(maxp):
        L = list_page(off)
        for w in ((30, 90, 180) if back else ()):   # 補抓時遇到暫時連不上,等一下再試,不要整個停掉
            if L is not None: break
            print(f"  列表 offset {off} 連不上,{w} 秒後重試", flush=True); time.sleep(w); L = list_page(off)
        if not L: break
        todo = [k for k in L if "|".join(k) not in seen]
        if not todo:
            stale += 1
            if not back and stale >= 2: break     # 連續兩頁都抓過 → 後面也都抓過
        for c, d, s, f in todo:
            if d < SINCE: continue
            pg = get(f"{BASE}announcement?company={c}&date={d}&seq={s}&fund={f}&type=distribution")
            time.sleep(.6 if back else .35)
            if pg is None: continue                # 失敗的不記 seen,下次再試
            seen.add("|".join((c, d, s, f)))
            r = parse(pg)
            if not r: continue
            fill_amount(f, r)
            r += [f"{d[:4]}-{d[4:6]}-{d[6:]}", int(s)]
            L2 = [x for x in E.get(f, []) if not (x[0] and r[0] and x[0] == r[0]) and not (x[7] == r[7] and x[8] == r[8])]
            L2.append(r)                           # 同一次除息有預估/實際兩則公告時,留公告日較新的
            L2.sort(key=lambda x: (x[0] or x[7], x[7]), reverse=True)
            E[f] = L2[:KEEP]; new += 1
        if min(k[1] for k in L) < SINCE: break     # 已經翻到 2023/11 以前
        off += 10
        time.sleep(.35)
        if back and p % 20 == 0: print(f"  第 {p} 頁(offset {off}),目前 {len(E)} 檔、新增 {new} 筆", flush=True)
    res = {"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "cols": ["除息日", "每單位配息", "股利所得%", "利息所得%", "收益平準金%", "已實現資本利得%", "其他所得%", "公告日", "公告序號"],
           "note": "證交所 ETF e添富 收益分配公告的「(預估)收益分配組成占比」;投信表示僅供參考,實際以受益人收益分配通知為準",
           "etfs": E}
    with open(OUT, "w", encoding="utf-8") as fh: json.dump(res, fh, ensure_ascii=False, separators=(",", ":"))
    with open(SEEN, "w", encoding="utf-8") as fh: json.dump(sorted(seen, key=lambda k: k.split("|")[1])[-8000:], fh, separators=(",", ":"))
    print(f"div_mix: {len(E)} 檔 ETF,本次新增 {new} 筆", flush=True)


def fix():
    with open(OUT, encoding="utf-8") as fh: res = json.load(fh)
    with open(SEEN, encoding="utf-8") as fh: seen = json.load(fh)
    E = res["etfs"]; n = 0
    for f, rows in E.items():
        keep = []
        for r in rows:
            if not 90 <= sum(r[2:7]) <= 110:
                k = next((k for k in seen if k.endswith("|" + f) and k.split("|")[1] == r[7].replace("-", "") and k.split("|")[2] == str(r[8])), None)
                if k:
                    c, d, s, _ = k.split("|"); pg = get(f"{BASE}announcement?company={c}&date={d}&seq={s}&fund={f}&type=distribution"); time.sleep(.5)
                    r2 = parse(pg or "")
                    if r2: r = r2 + [r[7], r[8]]; n += 1
                    else: continue
                else: continue
            keep.append(fill_amount(f, r))
        E[f] = keep
    E = {f: v for f, v in E.items() if v}; res["etfs"] = E
    with open(OUT, "w", encoding="utf-8") as fh: json.dump(res, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"修正 {n} 筆;{len(E)} 檔;缺配息金額 {sum(1 for v in E.values() for r in v if r[1] is None)} 筆")


if __name__ == "__main__":
    if "--fix" in sys.argv: fix(); sys.exit()
    if "--test" in sys.argv:
        for u in sys.argv[2:]:
            print(u[-60:], parse(get(u) or ""))
    else:
        main()
