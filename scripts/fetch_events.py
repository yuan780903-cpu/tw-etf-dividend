"""法說會行事曆 + 內部人持股轉讓申報 -> data/events.json
  法說會:公開資訊觀測站 t100sb02_1(上市、上櫃,上個月～後 2 個月)
  內部人:證交所 t187ap12_L、櫃買 mopsfin_t187ap12_O(每日轉讓事前申報,累積保留 180 天)
"""
import json, os, re, sys, html, time, datetime as dt, urllib.request, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; OUT = os.path.join(DATA, "events.json")
TODAY = dt.date.today()
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"}
N = lambda x: float(str(x).replace(",", "")) if re.match(r"^-?[\d,.]+$", str(x).replace(",", "").strip() or "x") else 0.0
roc2iso = lambda s: (lambda m: f"{int(m[1]) + 1911}-{int(m[2]):02d}-{int(m[3]):02d}" if m else None)(re.match(r"(\d{3})\D?(\d{2})\D?(\d{2})", s or ""))

def conf(y, m, typek):
    body = urllib.parse.urlencode(dict(encodeURIComponent=1, step=1, firstin=1, off=1, TYPEK=typek, year=str(y - 1911), month=f"{m:02d}", co_id="")).encode()
    for i in range(3):
        try: s = urllib.request.urlopen(urllib.request.Request("https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1", data=body, headers=UA), timeout=90).read().decode("utf-8", "ignore"); break
        except Exception as e: print("  重試", y, m, typek, e); time.sleep(10)
    else: return []
    out = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", s, re.S | re.I):
        td = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S | re.I)]
        if len(td) >= 6 and re.match(r"^\d{4}$", td[0]):
            pdf = re.search(r"([0-9A-Z]+M\d{3}\.pdf)", r)
            out.append(dict(c=td[0], n=td[1], d=roc2iso(td[2].replace("/", "")) or roc2iso(td[2]), t=td[3], loc=td[4][:40], say=td[5][:120], m="上市" if typek == "sii" else "上櫃",
                            pdf=f"https://mopsov.twse.com.tw/nas/STR/{pdf[1]}" if pdf else None))
    time.sleep(4); return out

def insider():
    rows = []
    for url, mk in (("https://openapi.twse.com.tw/v1/opendata/t187ap12_L", "上市"), ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap12_O", "上櫃")):
        try: data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=90).read())
        except Exception as e: print("  內部人失敗", mk, e); continue
        for r in data:
            g = lambda *ks: next((r[k] for k in ks if k in r and r[k] not in (None, "")), "")
            c = g("公司代號", "SecuritiesCompanyCode")
            if not c: continue
            rows.append(dict(d=roc2iso(g("出表日期", "Date")), c=c, n=g("公司名稱", "CompanyName"), who=g("申報人身分", "申請人身分"), name=g("姓名"), how=g("預定轉讓方式及股數-轉讓方式"),
                             sh=N(g("預定轉讓總股數-自有持股")), before=N(g("目前持有股數-自有持股")), after=N(g("預定轉讓後持股-自有持股")), to=g("受讓人"), per=g("有效轉讓期間"), m=mk))
    return rows

def main():
    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    confs = []
    for k in (-1, 0, 1, 2):
        y, m = TODAY.year + (TODAY.month - 1 + k) // 12, (TODAY.month - 1 + k) % 12 + 1
        for typek in ("sii", "otc"): confs += conf(y, m, typek)
    confs = sorted({(x["c"], x["d"], x["t"]): x for x in confs if x["d"]}.values(), key=lambda x: (x["d"], x["t"]))
    ins = insider(); cut = (TODAY - dt.timedelta(days=180)).isoformat()
    key = lambda x: (x["d"], x["c"], x["name"], x["to"], x["sh"])
    allins = {key(x): x for x in old.get("insider", []) + ins if x.get("d") and x["d"] >= cut}
    insl = sorted(allins.values(), key=lambda x: (x["d"], x["sh"]), reverse=True)
    fh.save(OUT, dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), conf=confs, insider=insl,
                      deadlines=[["每月 10 日前", "上市櫃公司公布上個月營收"], ["3 月 31 日", "年報（全年財報）與第 4 季"], ["5 月 15 日", "第 1 季財報"], ["8 月 14 日", "第 2 季（半年報）"], ["11 月 14 日", "第 3 季財報"]]))
    print(f"events.json:法說會 {len(confs)} 場、內部人申報 {len(insl)} 筆(今日 {len(ins)})")

if __name__ == "__main__":
    main()
