"""總經現況 vs 基準值 → 對應的大盤指數 -> data/macro_map.json
每個總經指標:
  基準值(合理值)＋容許範圍 → 判斷目前「高於 / 接近 / 低於」基準
  歷史對照(2010 年起每月):指標處在「目前這一區」與「接近基準」時,加權指數之後 6 個月平均漲跌、上漲機率
  對應的指數 = 目前加權指數 ×(1 + 該區歷史平均 6 個月漲跌)
避免偷看未來:指標當月數字約下個月才公布,所以從「公布後那個月底」開始算之後 6 個月
資料:data/macro.json(FRED、國發會、經濟部)、Yahoo 加權指數月線(1997 年起)
"""
import json, os, sys, time, datetime as dt, urllib.request, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; H = 6                                     # 看之後 6 個月

# 代號, 來源, 名稱, 單位, 換算, 基準, 容許範圍, 基準說明, 高於基準對股市(+1 好 / -1 不好 / 0 看情況), 白話
SPEC = [
  ("CPIAUCSL", "s", "🇺🇸 CPI 年增率", "%", 1, 2.0, .5, "聯準會的目標 2%", -1, "物價漲太快，聯準會就不敢降息"),
  ("PCEPILFE", "s", "🇺🇸 核心 PCE 年增率", "%", 1, 2.0, .5, "聯準會最看重的通膨，目標 2%", -1, "聯準會降息與否最看這個"),
  ("PPIFIS", "s", "🇺🇸 PPI 年增率", "%", 1, 2.0, 1.0, "和 CPI 目標一致", -1, "上游成本，會慢慢轉嫁到 CPI"),
  ("PAYEMS", "s", "🇺🇸 非農新增就業", "萬人", .1, 15, 5, "每月新增約 15 萬人＝景氣正常", 0, "太少怕衰退、太多怕過熱不降息"),
  ("UNRATE", "s", "🇺🇸 失業率", "%", 1, 4.2, .3, "聯準會估計的長期正常水準", -1, "上升太快是衰退訊號"),
  ("ICSA", "s", "🇺🇸 初領失業救濟金", "萬人", 1e-4, 25, 2.5, "每週約 25 萬人＝就業正常", -1, "最即時的裁員溫度計"),
  ("A191RL1Q225SBEA", "s", "🇺🇸 GDP 季增年率", "%", 1, 2.0, 1.0, "美國長期正常成長約 2%", 1, "經濟成長速度"),
  ("RSAFS", "s", "🇺🇸 零售銷售年增率", "%", 1, 4.0, 1.5, "含物價的正常成長約 4%", 1, "消費占美國經濟七成"),
  ("UMCSENT", "s", "🇺🇸 密大消費者信心", "", 1, None, 7, "2010 年以來的中位數", 1, "大家敢不敢花錢"),
  ("DGS10", "s", "🇺🇸 美債 10 年殖利率", "%", 1, 4.0, .4, "近年股市的分水嶺", -1, "利率越高，股票越不值錢"),
  ("GACDFSA066MSFRBPHI", "s", "🇺🇸 費城聯準會製造業指數", "", 1, 0, 5, "0 以上＝擴張", 1, "工廠景氣（PMI 參考）"),
  ("XTEXVA01CNM667S", "s", "🇨🇳 中國出口年增率", "%", 1, 5, 5, "正常成長約 5%", 1, "影響台灣供應鏈訂單"),
  ("LIGHT", "tw", "🇹🇼 景氣對策信號", "分", 1, 27, 4, "綠燈 23～31 分的中間", 0, "國發會的景氣紅綠燈"),
  ("EXPORT", "tw", "🇹🇼 出口年增率", "%", 1, 5, 5, "正常成長約 5%", 1, "台灣企業賺錢的主要來源"),
  ("ORDERS", "tw", "🇹🇼 外銷訂單年增率", "%", 1, 5, 5, "正常成長約 5%", 1, "領先出口 1～3 個月"),
  ("ORDERIDX", "tw", "🇹🇼 外銷訂單動向指數", "", 1, 50, 3, "50 以上＝廠商看好", 1, "廠商對未來接單的感覺（PMI 參考）"),
  ("IPI", "tw", "🇹🇼 工業生產年增率", "%", 1, 3, 4, "正常成長約 3%", 1, "工廠實際做了多少東西"),
  ("M1B", "tw", "🇹🇼 M1B 年增率", "%", 1, 5, 2, "長期平均約 5%", 1, "市場上的活錢，多了容易流進股市"),
  ("LOANRATE", "tw", "🇹🇼 五大銀行放款利率", "%", 1, None, .15, "2010 年以來的中位數", -1, "國內借錢成本"),
  ("TWUNEMP", "tw", "🇹🇼 台灣失業率", "%", 1, 3.7, .3, "近年正常水準", -1, "國內就業狀況"),
]

def taiex_monthly():
    """加權指數月線(月底收盤):Yahoo ^TWII,抓不到沿用快取"""
    p = os.path.join(DATA, "taiex_m.json")
    try:
        j = json.loads(urllib.request.urlopen(urllib.request.Request("https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?range=max&interval=1mo", headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read())["chart"]["result"][0]
        rows = {}
        for t, c in zip(j["timestamp"], j["indicators"]["quote"][0]["close"]):
            if c: rows[(dt.datetime.utcfromtimestamp(t) + dt.timedelta(hours=8)).strftime("%Y-%m")] = round(c, 2)
        if len(rows) > 200: fh.save(p, rows); return rows
    except Exception as e: print("  Yahoo 月線失敗,沿用快取:", e)
    return json.load(open(p)) if os.path.exists(p) else {}

def monthly(rows, k=1):
    """日/週/季資料 → 每月平均;季資料往後補滿 3 個月"""
    g = {}
    for d, v in rows:
        if v is None: continue
        g.setdefault(d[:7], []).append(v * k)
    out = {m: sum(v) / len(v) for m, v in g.items()}
    ks = sorted(out)
    if len(ks) > 2 and all((int(b[:4]) * 12 + int(b[5:])) - (int(a[:4]) * 12 + int(a[5:])) == 3 for a, b in zip(ks[-4:], ks[-3:])):   # 季資料
        for m in list(ks):
            y, mm = int(m[:4]), int(m[5:])
            for a in (1, 2):
                n = y * 12 + mm - 1 + a; out.setdefault(f"{n // 12}-{n % 12 + 1:02d}", out[m])
    return out

def madd(m, a):
    n = int(m[:4]) * 12 + int(m[5:]) - 1 + a
    return f"{n // 12}-{n % 12 + 1:02d}"

def main():
    MC = json.load(open(os.path.join(DATA, "macro.json"))); P = taiex_monthly()
    pm = sorted(P); now_idx, now_m = P[pm[-1]], pm[-1]
    try:
        M = json.load(open(os.path.join(DATA, "market.json"))); now_idx, idx_d = M["rows"][-1][1], M["rows"][-1][0]
    except Exception: idx_d = now_m
    def fwd(m):                                            # 指標月份 m:下個月底公布後,再看 H 個月
        a, b = madd(m, 1), madd(m, 1 + H)
        return (P[b] / P[a] - 1) * 100 if a in P and b in P else None
    allr = [fwd(m) for m in pm if m >= "2010-01" and fwd(m) is not None]
    ctrl = dict(r=round(st.mean(allr), 2), w=round(sum(x > 0 for x in allr) / len(allr) * 100), n=len(allr))
    out = []
    for sid, src, name, unit, k, base, band, why, good, plain in SPEC:
        s = (MC.get(src) or {}).get(sid)
        if not s or not s.get("rows"): print("  缺", sid); continue
        mv = monthly(s["rows"], k); ms = sorted(mv)
        if base is None: base = round(st.median(mv[m] for m in ms), 2)
        cur_m = ms[-1]; cur = round(mv[cur_m], 2)
        stt = lambda v: "高於" if v > base + band else "低於" if v < base - band else "接近"
        def grp(state):
            mm = [m for m in ms if stt(mv[m]) == state and fwd(m) is not None]; xs = [fwd(m) for m in mm]
            yrs = len({m[:4] for m in mm})                  # 樣本分散在幾個年份:太集中＝可能只是剛好碰上某段行情
            rel = "高" if len(xs) >= 40 and yrs >= 6 else "中" if len(xs) >= 20 and yrs >= 4 else "低"
            return dict(r=round(st.mean(xs), 2), w=round(sum(x > 0 for x in xs) / len(xs) * 100), n=len(xs), yrs=yrs, rel=rel) if len(xs) >= 6 else dict(r=None, w=None, n=len(xs), yrs=yrs, rel="低")
        S = stt(cur); gc, gb = grp(S), grp("接近")
        cnt = {x: sum(1 for m in ms if stt(mv[m]) == x) for x in ("高於", "接近", "低於")}
        ic = round(now_idx * (1 + gc["r"] / 100)) if gc["r"] is not None else None
        ib = round(now_idx * (1 + gb["r"] / 100)) if gb["r"] is not None else None
        u = unit if unit in ("%", "分") else (" " + unit if unit else "")
        f = lambda v: f"{v:,.2f}".rstrip("0").rstrip(".") + u
        say = f"目前 {f(cur)}，{S}基準 {f(base)}（{why}）。"
        if gc["r"] is not None: say += f"2010 年以來指標「{S}基準」的 {gc['n']} 個月，台股之後 6 個月平均 {gc['r']:+.1f}%（上漲機率 {gc['w']}%）"
        if S != "接近" and gb["r"] is not None: say += f"；「接近基準」時平均 {gb['r']:+.1f}%（上漲機率 {gb['w']}%）"
        say += "。"
        if gc.get("rel") == "低": say += f"（樣本只有 {gc['n']} 個月、集中在 {gc['yrs']} 個年份，可能只是剛好碰上某段行情，參考性低）"
        out.append(dict(id=sid, g="US" if src == "s" and not sid.startswith("XTEX") else "CN" if sid.startswith("XTEX") else "TW", name=name, unit=unit, plain=plain,
                        cur=cur, curM=cur_m, base=base, band=band, why=why, good=good, state=S, gap=round(cur - base, 2),
                        gc=gc, gb=gb, cnt=cnt, idxCur=ic, idxBase=ib, say=say, since=ms[0]))
    vs = [x["gc"]["r"] for x in out if x["gc"]["r"] is not None and x["gc"].get("rel") != "低"]   # 綜合只用可信度中以上
    summ = dict(n=len(vs), med=round(st.median(vs), 2) if vs else None, idxMed=round(now_idx * (1 + st.median(vs) / 100)) if vs else None,
                better=sum(1 for x in out if x["gc"]["r"] is not None and x["gc"].get("rel") != "低" and x["gc"]["r"] > ctrl["r"] + 1), worse=sum(1 for x in out if x["gc"]["r"] is not None and x["gc"].get("rel") != "低" and x["gc"]["r"] < ctrl["r"] - 1))
    fh.save(os.path.join(DATA, "macro_map.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), idx=now_idx, idxD=idx_d, h=H, ctrl=ctrl, sum=summ, rows=out,
            note="歷史對照為 2010 年起每月統計(指標公布後才開始算,不偷看未來);對應指數＝目前加權指數×(1＋該區之後 6 個月平均漲跌),是歷史平均不是預測;基準值為政策目標或長期常態"))
    print(f"macro_map.json:{len(out)} 項;對照組 6 個月平均 {ctrl['r']}%;目前各指標狀態對應的中位數 {summ['med']}% → {summ['idxMed']}")
    for x in out: print(f"  {x['name']} {x['cur']} {x['state']} 基準 {x['base']}:目前區 {x['gc']} 基準區 {x['gb']} → {x['idxCur']} / {x['idxBase']}")

if __name__ == "__main__":
    main()
