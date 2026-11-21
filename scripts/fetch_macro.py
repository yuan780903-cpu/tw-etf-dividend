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
    fh.save(os.path.join(fh.DATA, "macro.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), s=out, fed=dec))
    print(f"macro.json:{len(out)} 項;聯準會決策 {len(dec)} 次,最近 {dec[-1] if dec else None}")

if __name__ == "__main__":
    main()
