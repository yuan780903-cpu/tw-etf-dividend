"""美國總經指標 -> data/macro.json(來源:聖路易聯準銀行 FRED 公開 CSV,免金鑰)
月資料存 2010 起;日資料近 3 年保留每日、更早取每週最後一筆
"""
import csv, io, json, os, sys, time, datetime as dt, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
SER = {  # id: (轉換, 頻率)  轉換: lvl 原值 / yoy 年增率 / chg 月增量
    "CPIAUCSL": ("yoy", "m"), "CPILFESL": ("yoy", "m"), "PCEPILFE": ("yoy", "m"), "PPIFIS": ("yoy", "m"),
    "PAYEMS": ("chg", "m"), "UNRATE": ("lvl", "m"), "ICSA": ("lvl", "w"), "A191RL1Q225SBEA": ("lvl", "q"),
    "RSAFS": ("yoy", "m"), "UMCSENT": ("lvl", "m"), "M2SL": ("yoy", "m"),
    "T10Y2Y": ("lvl", "d"), "DGS10": ("lvl", "d"), "DGS2": ("lvl", "d"), "BAMLH0A0HYM2": ("lvl", "d"), "T5YIE": ("lvl", "d"),
    "GACDFSA066MSFRBPHI": ("lvl", "m"), "XTEXVA01CNM667S": ("yoy", "m"),
    "DFEDTARU": ("lvl", "d"), "DFEDTARL": ("lvl", "d"), "EFFR": ("lvl", "d"),
}
START = "2009-01-01"
_OP = urllib.request.build_opener()   # 不用全域 opener(帶瀏覽器 UA 會被 FRED 擋到 timeout)

def fred(i):
    for k in range(3):
        try:
            t = _OP.open(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={i}&cosd={START}", timeout=60).read().decode()
            rows = [(r[0], float(r[1])) for r in csv.reader(io.StringIO(t)) if len(r) == 2 and r[1] not in ("", ".") and r[0][:1].isdigit()]
            if rows: return rows
        except Exception as e:
            print(" ", i, "重試", e); time.sleep(5 * (k + 1))
    return []

def taiwan():
    """台灣總經:國發會景氣指標(燈號、出口、M1B、失業率、外銷訂單動向)+ 經濟部外銷訂單金額"""
    import zipfile, io
    tw = {}
    def ser(name, rows, tf="lvl"):
        rows = sorted(rows)
        if tf == "yoy":
            m = dict(rows); rows = [(d, round((v / m[f"{int(d[:4]) - 1}{d[4:]}"] - 1) * 100, 2)) for d, v in rows if m.get(f"{int(d[:4]) - 1}{d[4:]}")]
        tw[name] = dict(rows=[[f"{d[:4]}-{d[4:6]}-01", v] for d, v in rows if d >= "201001"])
    try:
        b = urllib.request.urlopen(urllib.request.Request("https://ws.ndc.gov.tw/Download.ashx?u=LzAwMS9hZG1pbmlzdHJhdG9yLzEwL3JlbGZpbGUvNTc4MS82MzkyL2VhMjM1YmQ5LWQwNTItNGE2OS1hYmZjLWQ1Yzc4NWQzZDBlMi56aXA%3d&n=5pmv5rCj5oyH5qiZ5Y%2bK54eI6JmfLnppcA%3d%3d&icon=.zip", headers={"User-Agent": "Mozilla/5.0"}), timeout=90).read()
        z = zipfile.ZipFile(io.BytesIO(b)); T = {}
        for i in z.infolist():
            if i.filename.startswith("schema") or i.filename == "manifest.csv": continue
            rows = list(csv.reader(io.StringIO(z.read(i).decode("utf-8-sig", "ignore"))))
            T[i.filename] = (rows[0], rows[1:])
        def col(fname, cname):
            h, rows = T[fname]; k = h.index(cname); out = []
            for r in rows:
                try: out.append((r[0], float(r[k])))
                except (ValueError, IndexError): pass
            return out
        sig = T["景氣指標與燈號.csv"]; h = sig[0]; ks, kc = h.index("景氣對策信號綜合分數"), h.index("景氣對策信號")
        tw["LIGHT"] = dict(rows=[[f"{r[0][:4]}-{r[0][4:6]}-01", float(r[ks])] for r in sig[1] if r[ks] not in ("", "-") and r[0] >= "201001"], color={r[0]: r[kc] for r in sig[1][-3:]})
        tw["LIGHT"]["last_color"] = next((r[kc] for r in reversed(sig[1]) if r[kc] not in ("", "-")), None)
        ser("EXPORT", col("同時指標構成項目.csv", "海關出口值(十億元)"), "yoy")
        ser("M1B", col("領先指標構成項目.csv", "貨幣總計數M1B(百萬元)"), "yoy")
        ser("TWUNEMP", col("落後指標構成項目.csv", "失業率(%)"))
        ser("ORDERIDX", col("領先指標構成項目.csv", "外銷訂單動向指數(以家數計)"))
        ser("LOANRATE", col("落後指標構成項目.csv", "五大銀行新承做放款平均利率(年息百分比)"))
        ser("IPI", col("同時指標構成項目.csv", "工業生產指數(Index2021=100)"), "yoy")
    except Exception as e: print("  國發會景氣指標失敗", e)
    try:
        t = urllib.request.urlopen(urllib.request.Request("https://service.moea.gov.tw/EE520/opendata/b.csv", headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode("utf-8-sig", "ignore")
        rows = []
        for r in list(csv.reader(io.StringIO(t)))[1:]:
            if len(r) >= 3 and r[1].isdigit() and len(r[1]) == 5: rows.append((f"{int(r[1][:3]) + 1911}{r[1][3:]}", float(r[2])))
        ser("ORDERS", rows, "yoy"); tw["ORDERS"]["amt"] = rows[-1][1] if rows else None
    except Exception as e: print("  外銷訂單失敗", e)
    for k in ("ORDERS", "LIGHT", "EXPORT", "M1B", "TWUNEMP", "ORDERIDX", "LOANRATE", "IPI"):   # 抓不到時沿用上次資料(經濟部擋雲端 IP)
        if not (tw.get(k) or {}).get("rows"):
            try:
                old = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "macro.json"), encoding="utf-8")).get("tw", {}).get(k)
                if old: tw[k] = old; print("  沿用舊資料", k)
            except Exception: pass
    print("  台灣總經:", "、".join(f"{k} {v['rows'][-1] if v.get('rows') else '-'}" for k, v in tw.items()))
    return tw

def thin(rows):
    cut = (dt.date.today() - dt.timedelta(days=365 * 3)).isoformat(); out, wk = [], {}
    for d, v in rows:
        if d >= cut: out.append((d, v)); continue
        y, w, _ = dt.date.fromisoformat(d).isocalendar(); wk[(y, w)] = (d, v)
    return sorted(wk.values()) + out

def main():
    out = {}
    for i, (tf, fq) in SER.items():
        raw = fred(i)
        if not raw: print("  失敗", i); continue
        if tf == "yoy":
            m = dict(raw); rows = []
            for d, v in raw:
                p = m.get(f"{int(d[:4]) - 1}{d[4:]}")
                if p: rows.append((d, round((v / p - 1) * 100, 2)))
            mom = round((raw[-1][1] / raw[-2][1] - 1) * 100, 2)
        elif tf == "chg":
            rows = [(raw[k][0], round(raw[k][1] - raw[k - 1][1], 1)) for k in range(1, len(raw))]; mom = None
        else:
            rows = raw; mom = None
        if fq == "d": rows = thin(rows)
        rows = [r for r in rows if r[0] >= "2010-01-01"]
        out[i] = dict(tf=tf, fq=fq, rows=[[d, v] for d, v in rows], mom=mom)
        print(f"  {i}: {len(rows)} 筆,最新 {rows[-1]}")
        time.sleep(.6)
    # 聯準會利率決策紀錄(目標區間上限變動日)
    dec = []
    up, lo = dict(fred("DFEDTARU")), dict(fred("DFEDTARL"))
    ds = sorted(up); prev = None
    for d in ds:
        if prev is not None and up[d] != prev: dec.append(dict(d=d, lo=lo.get(d), up=up[d], bp=round((up[d] - prev) * 100)))
        prev = up[d]
    fh.save(os.path.join(fh.DATA, "macro.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), s=out, fed=dec, tw=taiwan()))
    print(f"macro.json:{len(out)} 項;聯準會決策 {len(dec)} 次,最近 {dec[-1] if dec else None}")

if __name__ == "__main__":
    main()
