"""個股股利排行與除權息行事曆 -> data/stock_div.json
來源:公開資訊觀測站「股利分派情形彙總表」(t05st09sub,上市+上櫃,依股利所屬年度)
      證交所 TWT48U/TWT49U、櫃買 PrePost/exDailyQ(除權息預告與結果)
殖利率用目前股價;配發率=現金股利總額 ÷ 當年度歸屬母公司淨利
"""
import json, os, re, sys, html, time, datetime as dt, urllib.request, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; RAW = os.path.join(DATA, "divs"); os.makedirs(RAW, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"}
TODAY = dt.date.today(); ROC = TODAY.year - 1911
N = lambda x: float(x.replace(",", "")) if x and re.match(r"^-?[\d,.]+$", x.replace(",", "")) else 0.0

def mops_year(roc, typek):
    p = os.path.join(RAW, f"div_{roc}_{typek}.json")
    if os.path.exists(p) and roc < ROC - 1: return json.load(open(p))    # 兩年前以前的資料不會再變,用快取
    body = urllib.parse.urlencode(dict(step=1, TYPEK=typek, YEAR=str(roc), first="", qryType="")).encode()
    for i in range(4):
        try:
            s = urllib.request.urlopen(urllib.request.Request("https://mopsov.twse.com.tw/server-java/t05st09sub", data=body, headers=UA), timeout=180).read().decode("cp950", "ignore"); break
        except Exception as e:
            print("  重試", roc, typek, e); time.sleep(15 * (i + 1))
    else:
        return json.load(open(p)) if os.path.exists(p) else []
    rows = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", s, re.S | re.I):
        td = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", x))).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S | re.I)]
        m = re.match(r"^(\d{4})\s*-\s*(.+)$", td[0]) if td else None
        if not m or len(td) < 17: continue
        rows.append(dict(c=m.group(1), n=m.group(2), st=td[1], per=td[2], rng=td[3], seq=td[4], bd=td[5], ni=N(td[8]),
                         cash=N(td[11]) + N(td[12]), tot=N(td[13]), stk=N(td[14]) + N(td[15])))
    if rows: fh.save(p, rows)
    print(f"股利 {roc} {typek}: {len(rows)} 筆"); time.sleep(5)
    return rows

def jget(url):
    for i in range(3):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=90).read())
        except Exception as e:
            if i == 2: print("  失敗", url[:80], e); return None
            time.sleep(5)
roc2iso = lambda s: (lambda m: f"{int(m[1]) + 1911}-{int(m[2]):02d}-{int(m[3]):02d}" if m else None)(re.match(r"(\d{2,3})\D+(\d{1,2})\D+(\d{1,2})", s or ""))

def calendar():
    up, past = [], []
    d = jget("https://www.twse.com.tw/rwd/zh/exRight/TWT48U?response=json") or {}
    for r in d.get("data", []):
        cash = re.sub(r"<[^>]+>", "", r[7]); up.append(dict(d=roc2iso(r[0]), c=r[1], n=r[2], k=r[3], cash=N(cash) if N(cash) else None, stk=N(r[4]) or None, note=None if N(cash) else cash.strip(), m="上市"))
    d = jget("https://www.tpex.org.tw/web/stock/exright/preAnnounce/PrePost_result.php?l=zh-tw&o=json") or {}
    for t in d.get("tables", []):
        for r in t.get("data", []):
            up.append(dict(d=roc2iso(r[0]), c=r[1], n=r[2], k=r[3].replace("除", ""), cash=N(r[7]) or None, stk=N(r[4]) or None, m="上櫃"))
    s, e = f"{TODAY.year}0101", TODAY.strftime("%Y%m%d")
    d = jget(f"https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={s}&endDate={e}&response=json") or {}
    for r in d.get("data", []):
        past.append(dict(d=roc2iso(r[0]), c=r[1], n=r[2], k=r[6], before=N(r[3]), ref=N(r[4]), val=N(r[5]), m="上市"))
    d = jget(f"https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php?l=zh-tw&d={ROC}/01/01&ed={ROC}/{TODAY.month:02d}/{TODAY.day:02d}&o=json") or {}
    for t in d.get("tables", []):
        for r in t.get("data", []):
            past.append(dict(d=roc2iso(r[0]), c=r[1], n=r[2], k=r[8], before=N(r[3]), ref=N(r[4]), val=N(r[7]), m="上櫃"))
    up = [x for x in up if x["d"] and x["d"] >= TODAY.isoformat()]; up.sort(key=lambda x: x["d"]); past.sort(key=lambda x: x["d"], reverse=True)
    print(f"除權息預告 {len(up)} 筆、今年已除權息 {len(past)} 筆"); return up, past

def main():
    F = json.load(open(os.path.join(DATA, "fund", "fundamentals.json")))["companies"]
    years = list(range(ROC - 5, ROC + 1)); stocks = {}
    for roc in years:
        y = str(roc + 1911); seen = {}
        for typek in ("sii", "otc"):
            for r in mops_year(roc, typek):
                seen[(r["c"], r["rng"])] = r                              # 同一期別取最後一筆(較新的決議)
        for (c, rng), r in seen.items():
            s = stocks.setdefault(c, dict(n=r["n"], y={})); a = s["y"].setdefault(y, dict(cash=0.0, stk=0.0, tot=0.0, k=0, st=""))
            a["cash"] += r["cash"]; a["stk"] += r["stk"]; a["tot"] += r["tot"]; a["k"] += 1 if (r["cash"] or r["stk"]) else 0; a["st"] = r["st"]
            if r["per"].endswith("年度") and r["ni"]: a["ni"] = r["ni"]
    for c, s in stocks.items():
        f = F.get(c) or {}; s["px"] = f.get("px"); s["ind"] = f.get("ind"); s["mkt"] = f.get("mkt")
        for y, a in s["y"].items():
            fy = (f.get("y") or {}).get(y) or {}
            ni = a.get("ni") or ((fy.get("niP") or 0) * 1000)
            a["eps"] = fy.get("eps"); a["pay"] = round(a["tot"] / ni * 100, 1) if ni and ni > 0 and a["tot"] else None
            a["cash"] = round(a["cash"], 4); a["stk"] = round(a["stk"], 4); a["tot"] = round(a["tot"])
            a.pop("ni", None)
    up, past = calendar()
    out = dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), years=[str(r + 1911) for r in years], stocks=stocks, up=up, past=past[:2000],
               note="股利依「股利所屬年度」歸戶，同一年度多次配息會加總；殖利率用目前股價計算。")
    fh.save(os.path.join(DATA, "stock_div.json"), out)
    yy = str(ROC + 1911 - 1)
    print(f"stock_div.json:{len(stocks)} 家;{yy} 年度配現金 {sum(1 for s in stocks.values() if s['y'].get(yy, {}).get('cash'))} 家")

if __name__ == "__main__":
    main()
