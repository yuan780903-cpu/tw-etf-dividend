"""大盤儀表板:交叉分析 -> data/market_analysis.json
讀 data/market.json + data/global.json + data/taiex.json,計算:
  1. 指標卡:目前值、5 年百分位、燈號、白話說明(基準值/高於/低於/現在)
  2. 大盤技術面
  3. 條件回測:某情況發生後 5/20/60 天大盤表現(以「事件」計,10 天內重複觸發只算一次)
  4. 相關性:各指標 vs 大盤未來 20 天報酬;全球指數 vs 台股
  5. 四象限:估算維持率高低 × 外資 20 日買賣
  6. 預測區間:1 週 / 1 個月(68% / 95%)+ 多空分數 + 支撐壓力 + 歷史命中率
  7. 白話總結(之後 LINE 推播也用這份)
用法: python3 scripts/build_market_analysis.py
"""
import json, os, sys, math, datetime as dt, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import ta
DATA = os.path.join(os.path.dirname(HERE), "data")

M = json.load(open(os.path.join(DATA, "market.json")))
G = json.load(open(os.path.join(DATA, "global.json")))
COLS, ROWS = M["cols"], M["rows"]
IX = {c: i for i, c in enumerate(COLS)}
N = len(ROWS)
col = lambda c: [r[IX[c]] for r in ROWS]
D, TX = col("d"), col("tx")

def r2(x, n=2): return None if x is None else round(x, n)
def pct_rank(vals, v):
    v0 = [x for x in vals if x is not None]
    return None if v is None or not v0 else round(sum(1 for x in v0 if x <= v) / len(v0) * 100, 1)
def quantile(vals, q):
    v0 = sorted(x for x in vals if x is not None)
    return v0[min(len(v0) - 1, max(0, int(q * (len(v0) - 1))))] if v0 else None
def last(vals):
    for i in range(len(vals) - 1, -1, -1):
        if vals[i] is not None: return vals[i], i
    return None, None
def chg(vals, i, n):
    return (vals[i] / vals[i - n] - 1) * 100 if i - n >= 0 and vals[i] and vals[i - n] else None
def fwd(i, n): return (TX[i + n] / TX[i] - 1) * 100 if i + n < N else None

# ---------- 衍生序列 ----------
fiit = [a + (b or 0) if a is not None else None for a, b in zip(col("ffi"), col("fit"))]   # 外資＋投信台指期淨未平倉:扣掉投信槓桿 ETF 與外資的對作,才是真實淨空
mAmt, fi, ffi, vixUs, vixTw, keep, below, mKeep = col("mAmt"), col("fi"), col("ffi"), col("vixUs"), col("vixTw"), col("keep"), col("below"), col("mKeep")
ret1 = [None] + [(TX[i] / TX[i - 1] - 1) * 100 for i in range(1, N)]
def rvol(i, n=20):
    xs = [math.log(TX[k] / TX[k - 1]) for k in range(max(1, i - n + 1), i + 1)]
    return st.pstdev(xs) * math.sqrt(252) * 100 if len(xs) >= 10 else None
RV = [rvol(i) for i in range(N)]
def ma(i, n): return sum(TX[i - n + 1:i + 1]) / n if i >= n - 1 else None
MA20, MA60, MA240 = [ma(i, 20) for i in range(N)], [ma(i, 60) for i in range(N)], [ma(i, 240) for i in range(N)]
BIAS60 = [(TX[i] / MA60[i] - 1) * 100 if MA60[i] else None for i in range(N)]
DD60 = [(TX[i] / max(TX[max(0, i - 59):i + 1]) - 1) * 100 for i in range(N)]
mChg1 = [chg(mAmt, i, 1) for i in range(N)]
mChg20 = [chg(mAmt, i, 20) for i in range(N)]
fi5 = [sum(x or 0 for x in fi[max(0, i - 4):i + 1]) for i in range(N)]
fi20 = [sum(x or 0 for x in fi[max(0, i - 19):i + 1]) for i in range(N)]
streak = []
for i in range(N):                                   # 外資連買(+)/連賣(-)天數
    s = 0
    if fi[i] is not None:
        prev = streak[-1] if streak else 0
        s = (prev + 1 if prev > 0 else 1) if fi[i] > 0 else (prev - 1 if prev < 0 else -1) if fi[i] < 0 else 0
    streak.append(s)
def rsi_at(i, n=14):
    if i < n * 3: return None
    seg = TX[max(0, i - 250):i + 1]; g = l = 0
    for k in range(1, n + 1):
        d = seg[k] - seg[k - 1]; g += max(d, 0); l += max(-d, 0)
    g, l = g / n, l / n
    for k in range(n + 1, len(seg)):
        d = seg[k] - seg[k - 1]; g = (g * (n - 1) + max(d, 0)) / n; l = (l * (n - 1) + max(-d, 0)) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)
RSI = [rsi_at(i) for i in range(N)]

# 全球指數:對齊台股日期(美股用「前一個美股交易日」)
def gser(sym):
    rows = G["idx"].get(sym, {}).get("rows", [])
    return dict(rows), [d for d, _ in rows]
def prev_on_or_before(dates, d):
    lo, hi = 0, len(dates) - 1; ans = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if dates[mid] < d: ans = dates[mid]; lo = mid + 1
        else: hi = mid - 1
    return ans
sox, sox_d = gser("^SOX")
SOX_PREV = []                                         # 台股某天開盤前,費半最近一晚的漲跌%
for d in D:
    p = prev_on_or_before(sox_d, d)
    if p:
        k = sox_d.index(p)
        SOX_PREV.append((sox[p] / sox[sox_d[k - 1]] - 1) * 100 if k > 0 else None)
    else: SOX_PREV.append(None)

# ---------- 1. 指標卡 ----------
def level(p, hi_bad=True, warn=(75, 90)):
    """p=百分位;hi_bad=數值越高越危險"""
    if p is None: return "na"
    x = p if hi_bad else 100 - p
    return "red" if x >= warn[1] else "amber" if x >= warn[0] else "green"

def card(key, name, unit, vals, explain, base, above, below_, hi_bad, now_fn, fmt=2, warn=(75, 90), fixed=None):
    v, i = last(vals)
    p = pct_rank(vals, v)
    lv = fixed(v) if fixed else level(p, hi_bad, warn)
    n = sum(1 for x in vals if x is not None)
    return dict(key=key, name=name, unit=unit, value=r2(v, fmt), date=D[i] if i is not None else None, pct=p, n=n,
                short=n < 250, level=lv, explain=explain, base=base, above=above, below=below_, now=now_fn(v, p) if v is not None else "")

V = lambda x, n=0: f"{x:,.{n}f}"
cards = [
    card("keep", "整戶擔保維持率（官方）", "%", keep,
         "所有融資融券戶「抵押股票市值 ÷ 借款」，代表散戶槓桿還剩多少安全空間。",
         "130% 是追繳線；170% 以上正常（8～10 月多在 175～195%）；160～170% 警戒；160% 以下危險。",
         "槓桿寬鬆、還有加碼空間；太高也代表市場偏熱。", "越多人逼近追繳，「被迫賣股」的賣壓變大。", False,
         lambda v, p: f"目前 {v:.2f}%，" + ("已低於 160% 的危險線，斷頭賣壓仍在。" if v < 160 else "介於警戒區。" if v < 170 else "仍在正常範圍。"),
         fixed=lambda v: "red" if v < 160 else "amber" if v < 170 else "green"),
    card("below", "追繳戶數（維持率低於 130%）", "戶", below,
         "整戶維持率跌破 130%、被券商要求補錢的帳戶數；沒補就會被處分（斷頭）。",
         "平時 100～300 戶正常；700 戶以上異常；2,000 戶以上屬斷頭潮。",
         "接下來 2 個交易日內有斷頭賣壓，短線容易再殺一段；但斷頭潮出清後籌碼變乾淨，歷史上常在短期底部附近。",
         "籌碼穩定，沒有被迫賣壓。", True,
         lambda v, p: f"目前 {V(v)} 戶" + ("，屬斷頭潮等級。" if v >= 2000 else "，在異常區間。" if v >= 700 else "，在正常範圍。"), 0,
         fixed=lambda v: "red" if v >= 700 else "amber" if v >= 300 else "green"),
    card("mAmt", "融資餘額（上市）", "億", mAmt,
         "散戶借錢買股的總金額，代表散戶槓桿與追價熱度。",
         "看 5 年百分位與近 20 天變化；單日減少超過 3% 代表斷頭或大幅降槓桿。",
         "散戶追價、槓桿偏高，行情偏熱；下跌時賣壓也較重。", "槓桿已降、籌碼較乾淨，賣壓較輕。", True,
         lambda v, p: f"目前 {V(v)} 億，在 5 年第 {p:.0f} 百分位；近 20 天變化 {r2(last(mChg20)[0],1)}%。", 0),
    card("mKeep", "大盤融資維持率（估算）", "%", mKeep,
         "融資擔保股票市值 ÷ 融資金額（證交所資料自算）；算法與官方整戶維持率不同，看的是 5 年相對位置。",
         "5 年最低 10% 屬恐慌區；最高 10% 屬過熱區。",
         "融資戶帳上獲利多，偏熱。", "融資戶普遍虧損，接近恐慌區時常伴隨斷頭。", False,
         lambda v, p: f"目前 {v:.1f}%，在 5 年第 {p:.0f} 百分位。"),
    card("fi5", "外資近 5 日買賣超", "億", fi5,
         "外資是台股最大的資金，主導台積電等權值股方向。",
         "看 5 年百分位與連續買賣天數；連續賣超 5 天以上代表持續撤出。",
         "外資回補買進，權值股有撐，常是止跌訊號。", "外資持續撤出，指數承壓。", False,
         lambda v, p: f"近 5 日合計 {V(v)} 億，外資已連續{'買' if streak[-1] > 0 else '賣'}超 {abs(streak[-1])} 天。", 0),
    card("ffi", "外資台指期淨未平倉", "口", ffi,
         "外資在台指期「多單 − 空單」，代表外資的避險與看空程度。",
         "2024 年起投信槓桿 ETF（正 2）大量買期貨多單、外資常在對面避險，外資空單因此結構性變多，單看口數會高估看空程度；請搭配「外資＋投信」（真實淨空）與 🐻 外資空單分析判斷。",
         "外資偏多，期貨不會壓抑現貨。", "外資看空或積極避險；空單堆到極端時一旦回補，常引發急漲（軋空）。", False,
         lambda v, p: f"目前淨{'多' if v > 0 else '空'} {V(abs(v))} 口，在 5 年第 {p:.0f} 百分位；扣掉投信對作後真實淨空 {V(abs(fiit[-1] or 0))} 口，在近一年第 {pct_rank(fiit[-250:], fiit[-1]):.0f} 百分位（越低越偏空）。", 0),
    card("vixTw", "台指 VIX 恐慌指數", "", vixTw,
         "選擇權市場預期未來 30 天的波動幅度。",
         "20 以下平靜；20～30 緊張；30～40 恐慌；40 以上極度恐慌。",
         "指數上下震盪變大，預測區間跟著變寬；極度恐慌常接近短期底部（反向訊號，但不保證）。", "市場平靜，波動小。", True,
         lambda v, p: f"目前 {v:.2f}，" + ("極度恐慌。" if v >= 40 else "恐慌。" if v >= 30 else "緊張。" if v >= 20 else "平靜。"),
         fixed=lambda v: "red" if v >= 30 else "amber" if v >= 20 else "green"),
    card("vixUs", "美股 VIX", "", vixUs,
         "美股的恐慌指數，全球資金風險情緒的溫度計。",
         "15 以下樂觀；15～20 中性；20～30 緊張；30 以上恐慌。",
         "全球資金避險，外資容易賣台股。", "全球風險偏好高，資金願意進場。", True,
         lambda v, p: f"目前 {v:.2f}，在 5 年第 {p:.0f} 百分位。",
         fixed=lambda v: "red" if v >= 30 else "amber" if v >= 20 else "green"),
    card("rv", "台股 20 日實際波動率", "%", RV,
         "大盤最近 20 天實際震盪幅度（年化），5 年都有資料，可當恐慌指數的替代。",
         "15% 以下平靜；15～25% 正常；25% 以上劇烈。",
         "震盪劇烈，追高殺低風險大。", "盤勢平靜。", True,
         lambda v, p: f"目前 {v:.1f}%，在 5 年第 {p:.0f} 百分位。", 1),
]

# ---------- 2. 技術面 ----------
taiex = json.load(open(os.path.join(DATA, "taiex.json")))
tech = ta.analyze(taiex, [], None) or {}
i = N - 1
tech_view = dict(price=TX[i], date=D[i], chg=r2(ret1[i]), ma20=r2(MA20[i]), ma60=r2(MA60[i]), ma240=r2(MA240[i]),
                 bias60=r2(BIAS60[i]), dd60=r2(DD60[i]), rsi=r2(RSI[i], 1), k=tech.get("k"), d=tech.get("d"),
                 macdUp=tech.get("macdUp"), hi52=tech.get("hi52"), lo52=tech.get("lo52"), pos=tech.get("pos"), score=tech.get("score"))

# ---------- 3. 條件回測 ----------
pRV90 = quantile(RV, .9); pMK10 = quantile(mKeep, .1); pFI5_10 = quantile(fi5, .1); pFFI10 = quantile(fiit, .1)
CONDS = [
    ("rsi30", "大盤 RSI 低於 30（超賣）", lambda i: RSI[i] is not None and RSI[i] < 30),
    ("dd10", "比近 3 個月高點跌超過 10%", lambda i: DD60[i] <= -10),
    ("dd15", "比近 3 個月高點跌超過 15%", lambda i: DD60[i] <= -15),
    ("bias8", "跌破季線，且比季線低 8% 以上", lambda i: BIAS60[i] is not None and BIAS60[i] <= -8),
    ("mKeep10", "估算融資維持率創 5 年來前 10% 低", lambda i: mKeep[i] is not None and mKeep[i] <= pMK10),
    ("mDrop3", "融資一天減少超過 3%（斷頭潮）", lambda i: mChg1[i] is not None and mChg1[i] <= -3),
    ("mDrop20", "融資 1 個月內減少超過 10%（散戶大幅降槓桿）", lambda i: mChg20[i] is not None and mChg20[i] <= -10),
    ("fiStreak5", "外資連續賣超 5 天以上", lambda i: streak[i] <= -5),
    ("fi5low", "外資 1 週賣超金額創 5 年來前 10% 大", lambda i: fi5[i] <= pFI5_10),
    ("ffi10", "外資＋投信期貨真實淨空創 5 年來前 10% 多", lambda i: fiit[i] is not None and fiit[i] <= pFFI10),
    ("vixUs30", "美股 VIX 高於 30", lambda i: vixUs[i] is not None and vixUs[i] >= 30),
    ("rv90", "台股震盪程度創 5 年來前 10% 高", lambda i: RV[i] is not None and RV[i] >= pRV90),
    ("sox3", "前一晚費城半導體跌超過 3%", lambda i: SOX_PREV[i] is not None and SOX_PREV[i] <= -3),
    ("below700", "追繳戶數超過 700 戶（官方資料，8 月起）", lambda i: below[i] is not None and below[i] >= 700),
]
def stats(idx, h):
    xs = [fwd(i, h) for i in idx if fwd(i, h) is not None]
    if not xs: return None
    return dict(n=len(xs), avg=r2(st.mean(xs)), med=r2(st.median(xs)), win=r2(sum(1 for x in xs if x > 0) / len(xs) * 100, 0),
                worst=r2(min(xs)), best=r2(max(xs)))
base = {h: stats(range(N), h) for h in (5, 20, 60)}
events = []
for key, name, fn in CONDS:
    hits = [i for i in range(N) if fn(i)]
    ep, lastk = [], -99                               # 10 天內重複觸發只算同一次事件
    for k in hits:
        if k - lastk > 10: ep.append(k)
        lastk = k
    events.append(dict(key=key, name=name, days=len(hits), episodes=len(ep), active=fn(N - 1),
                       lastDate=D[ep[-1]] if ep else None, dates=[D[k] for k in ep][-8:],
                       h5=stats(ep, 5), h20=stats(ep, 20), h60=stats(ep, 60), small=len(ep) < 8))

# ---------- 4. 相關性 ----------
def corr(a, b):
    p = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(p) < 30: return None
    ra = {v: k for k, v in enumerate(sorted(set(x for x, _ in p)))}; rb = {v: k for k, v in enumerate(sorted(set(y for _, y in p)))}
    xs, ys = [ra[x] for x, _ in p], [rb[y] for _, y in p]
    mx, my = st.mean(xs), st.mean(ys); sx, sy = st.pstdev(xs), st.pstdev(ys)
    return r2(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / len(xs) / (sx * sy), 2) if sx and sy else None
F20 = [fwd(i, 20) for i in range(N)]
corr_fwd = [dict(key=k, name=n, rho=corr(v, F20)) for k, n, v in [
    ("rsi", "RSI", RSI), ("bias60", "季線乖離", BIAS60), ("dd60", "距 60 日高點", DD60), ("mKeep", "估算融資維持率", mKeep),
    ("mChg20", "融資 20 日變化", mChg20), ("fi20", "外資 20 日買賣超", fi20), ("ffi", "外資期貨淨未平倉", ffi),
    ("vixUs", "美股 VIX", vixUs), ("rv", "台股波動率", RV)]]

# 全球指數:報酬比較 + 與台股日報酬相關(美股用前一晚)
txd = dict(zip(D, TX))
def perf(rows, days):
    if len(rows) <= days: return None
    return r2((rows[-1][1] / rows[-1 - days][1] - 1) * 100)
def ytd(rows):
    y = rows[-1][0][:4]; prev = [v for d, v in rows if d < y + "-01-01"]
    return r2((rows[-1][1] / prev[-1] - 1) * 100) if prev else None
glob = []
tw_rows = [[d, v] for d, v in zip(D, TX)]
for sym, g in [("TAIEX", dict(name="台灣 加權指數", region="台灣", rows=tw_rows))] + list(G["idx"].items()):
    rows = g["rows"]
    if len(rows) < 30: continue
    item = dict(sym=sym, name=g["name"], region=g["region"], last=rows[-1][1], date=rows[-1][0],
                d1=perf(rows, 1), w1=perf(rows, 5), m1=perf(rows, 21), m3=perf(rows, 63), y1=perf(rows, 250), ytd=ytd(rows),
                monthly=[[d, v] for k, (d, v) in enumerate(rows) if k == len(rows) - 1 or rows[k + 1][0][:7] != d[:7]][-61:])
    if sym != "TAIEX":
        gd = dict(rows); gdates = [d for d, _ in rows]
        us = g["region"] == "美洲"
        a, b = [], []
        for k in range(max(1, N - 250), N):
            d = D[k]; ref = prev_on_or_before(gdates, d) if us else (d if d in gd else None)
            if not ref: continue
            j = gdates.index(ref)
            if j == 0: continue
            a.append((gd[ref] / gd[gdates[j - 1]] - 1)); b.append(ret1[k] / 100)
        if len(a) > 30:
            ma_, mb = st.mean(a), st.mean(b); cov = sum((x - ma_) * (y - mb) for x, y in zip(a, b)) / len(a)
            item["corr1y"] = r2(cov / (st.pstdev(a) * st.pstdev(b)), 2)
            item["lag"] = us
    glob.append(item)

# ---------- 5. 四象限 ----------
pMK50 = quantile(mKeep, .5)
def quad(i):
    if mKeep[i] is None: return None
    return ("H" if mKeep[i] >= pMK50 else "L") + ("B" if fi20[i] >= 0 else "S")
QN = {"HB": "槓桿健康＋外資買：順風", "HS": "槓桿健康＋外資賣：高檔轉弱", "LB": "槓桿受傷＋外資買：落底回升", "LS": "槓桿受傷＋外資賣：逆風殺盤"}
quads = []
for q, nm in QN.items():
    idx = [i for i in range(N) if quad(i) == q]
    quads.append(dict(q=q, name=nm, days=len(idx), h20=stats(idx, 20), now=quad(last(mKeep)[1]) == q))

# ---------- 6. 預測區間 ----------
iv = vixTw[-1] if vixTw[-1] else (vixUs[-1] * (st.mean([x for x in RV[-250:] if x]) / st.mean([x for x in vixUs[-250:] if x])) if vixUs[-1] else None)
rv_now = RV[-1]
sig_ann = (0.6 * iv + 0.4 * rv_now) if iv else rv_now      # 隱含波動(市場預期)為主、實際波動為輔
active = [e for e in events if e["active"] and not e["small"] and e["h20"] and e["h5"]]
def tilt(h):                                                 # 目前成立的歷史情境,平均「超額報酬」打五折當方向偏移
    if not active: return 0.0
    ex = [e[f"h{h}"]["avg"] - base[h]["avg"] for e in active]
    return 0.5 * st.mean(ex)
P = TX[-1]
def zcal(h):                                                 # 台股常有大漲大跌(肥尾):用過去 5 年實際結果校準區間寬度
    zs = []
    for k in range(60, N - h):
        if RV[k]: zs.append(abs(math.log(TX[k + h] / TX[k])) / (RV[k] / 100 * math.sqrt(h / 252)))
    zs.sort(); return zs[int(.68 * (len(zs) - 1))], zs[int(.95 * (len(zs) - 1))]
def band(h):
    s = sig_ann / 100 * math.sqrt(h / 252); mu = tilt(h) / 100; z1, z2 = zcal(h)
    f = lambda z: round(P * math.exp(mu + z * s))
    return dict(days=h, center=f(0), lo68=f(-z1), hi68=f(z1), lo95=f(-z2), hi95=f(z2), sigma=r2(s * 100), tilt=r2(mu * 100), z68=r2(z1), z95=r2(z2))
fc = dict(sigmaAnn=r2(sig_ann, 1), ivUsed=r2(iv, 1), rv=r2(rv_now, 1), w1=band(5), m1=band(20))
# 歷史命中率:過去每一天用「當時的實際波動率」畫 20 天區間,看 20 天後落在區間內的比例
hit68 = hit95 = tot = 0
for k in range(60, N - 20):
    if not RV[k]: continue
    s = RV[k] / 100 * math.sqrt(20 / 252); r = math.log(TX[k + 20] / TX[k])
    tot += 1; hit68 += abs(r) <= s; hit95 += abs(r) <= 1.96 * s
z1, z2 = zcal(20)
fc["backtest"] = dict(n=tot, raw68=r2(hit68 / tot * 100, 0), raw95=r2(hit95 / tot * 100, 0), z68=r2(z1), z95=r2(z2),
                      note=f"單純用波動率畫的區間,過去實際只命中 {hit68 / tot * 100:.0f}% / {hit95 / tot * 100:.0f}%(台股常有大漲大跌),已把寬度放大 {z1:.2f} / {z2 / 1.96:.2f} 倍校準到 68% / 95%")
# 多空分數(-100~100):技術 + 籌碼 + 情緒(反向)
comp = []
def add(name, v, why): comp.append(dict(name=name, v=round(max(-100, min(100, v))), why=why))
tscore = tech.get("score") or 50
add("技術面", (tscore - 50) * 2, f"均線、RSI、KD 等綜合分數 {tscore}（50 為中性）")
add("外資買賣股票", max(-100, min(100, fi5[-1] / max(1, abs(quantile(fi5, .05) or 1)) * 100)), f"近 5 日 {V(fi5[-1])} 億")
pf = pct_rank(fiit[-250:], last(fiit)[0]) or 50
add("外資期貨部位", (pf - 50) * 2, f"外資＋投信真實淨空 {V(abs(last(fiit)[0] or 0))} 口，空單多寡在近一年第 {100 - pf:.0f} 百分位（越高越偏空）")
mk = pct_rank(mKeep, last(mKeep)[0]) or 50
add("散戶融資", (50 - mk) * 1.2 if mk < 30 else (50 - mk) * 0.6, "融資戶虧損嚴重、賣壓接近出清，反而偏多" if mk < 30 else f"估算融資維持率在 5 年第 {mk:.0f} 百分位，槓桿不算過高也不算出清")
fear = pct_rank(RV, last(RV)[0]) or 50
add("恐慌程度", (fear - 50) * 1.2, "越恐慌越加分：歷史上極度恐慌後反彈機率較高")
score = round(st.mean(c["v"] for c in comp))
stance = "偏多" if score >= 35 else "中性偏多" if score >= 12 else "中性" if score > -12 else "中性偏空" if score > -35 else "偏空"
# 支撐 / 壓力
lv = [("月線(20日)", MA20[-1]), ("季線(60日)", MA60[-1]), ("年線(240日)", MA240[-1]), ("20日低點", min(TX[-20:])), ("20日高點", max(TX[-20:])),
      ("60日低點", min(TX[-60:])), ("60日高點", max(TX[-60:]))]
hi52, lo52 = max(TX[-250:]), min(TX[-250:])
lv += [(f"52週漲幅回檔 {int(f*1000)/10:g}%", hi52 - f * (hi52 - lo52)) for f in (.382, .5, .618, .786)]
lv += [("52週低點", lo52), ("52週高點", hi52)]
lv += [(f"整數關卡 {k:,}", k) for k in (int(P // 1000) * 1000, int(P // 1000 + 1) * 1000)]
sup = sorted([(n, round(v)) for n, v in lv if v and v < P], key=lambda x: -x[1])[:4]
res = sorted([(n, round(v)) for n, v in lv if v and v > P], key=lambda x: x[1])[:4]

# ---------- 7. 白話總結 ----------
say = []
w, m = fc["w1"], fc["m1"]
say.append(f"加權指數 {V(P, 2)}（{D[-1]}），比近 3 個月最高點{'下跌' if DD60[-1] < 0 else '持平'} {abs(DD60[-1]):.1f}%，{'跌破' if P < (MA60[-1] or 0) else '站上'}季線（近 3 個月平均價）。")
say.append(f"目前市場震盪{'很大' if fc['sigmaAnn'] >= 30 else '正常'}（一年約 ±{fc['sigmaAnn']:.0f}%），未來 1 週大概率落在 {V(w['lo68'])} ～ {V(w['hi68'])}，1 個月 {V(m['lo68'])} ～ {V(m['hi68'])}；極端情況 1 個月可能落在 {V(m['lo95'])} ～ {V(m['hi95'])}。")
for e in active[:4]:
    h = e["h20"]
    say.append(f"「{e['name']}」過去 5 年發生 {e['episodes']} 次，之後 1 個月大盤平均 {h['avg']:+.1f}%、上漲機率 {h['win']:.0f}%（平常是 {base[20]['avg']:+.1f}%、{base[20]['win']:.0f}%）。")
say.append(f"綜合多空分數 {score:+d}（-100 最空 ～ +100 最多），判讀：{stance}。")
say.append("以上為歷史資料統計推估，不構成任何投資建議。")

# ---------- 8. 市場恐慌度(0~100):各指標在「之前近 5 年」的百分位,方向統一成越高越恐慌,等權平均 ----------
import bisect
def exp_pct(vals, minn=120, win=1250):
    out, hist, srt = [], [], []
    for v in vals:
        if v is None: out.append(None); continue
        bisect.insort(srt, v); hist.append(v)
        if len(hist) > win: old = hist.pop(0); srt.pop(bisect.bisect_left(srt, old))
        out.append(None if len(hist) < minn else bisect.bisect_right(srt, v) / len(srt) * 100)
    return out
def rv_series(px, n=20):
    out = []
    for i in range(len(px)):
        xs = [math.log(px[k] / px[k - 1]) for k in range(max(1, i - n + 1), i + 1)]
        out.append(st.pstdev(xs) * math.sqrt(252) * 100 if len(xs) >= 10 else None)
    return out
def dd_series(px, n=252): return [(px[i] / max(px[max(0, i - n + 1):i + 1]) - 1) * 100 for i in range(len(px))]
def ffill(dates, src):
    out, lastv, ks, j = [], None, sorted(src), 0
    for d in dates:
        while j < len(ks) and ks[j] <= d: lastv = src[ks[j]]; j += 1
        out.append(lastv)
    return out
LEVELS = [(25, "平靜"), (50, "正常"), (75, "緊張"), (90, "恐慌"), (101, "極度恐慌")]
def lvl(x): return None if x is None else next(n for t, n in LEVELS if x < t)
def fear_block(name, idx_name, dates, px, comps, refs=()):
    n = len(dates); P = [c["p"] for c in comps]
    score = []
    for i in range(n):
        xs = []
        for p in P:                                  # 當天還沒公布的項目(例:融資 21:30 才有)沿用最近 3 天內的最新值
            v = next((p[k] for k in range(i, max(-1, i - 4), -1) if p[k] is not None), None)
            if v is not None: xs.append(v)
        score.append(round(st.mean(xs)) if len(xs) >= max(3, len(comps) - 2) else None)
    def ago(k): return score[-1 - k] if len(score) > k and score[-1 - k] is not None else None
    def fw(i, h): return (px[i + h] / px[i] - 1) * 100 if i + h < n else None
    def zst(idx):
        o = {"days": len(idx)}
        for h in (20, 60, 120):
            xs = [fw(i, h) for i in idx if fw(i, h) is not None]
            o[f"r{h}"] = dict(n=len(xs), med=r2(st.median(xs), 1), win=r2(sum(x > 0 for x in xs) / len(xs) * 100, 0)) if xs else None
        return o
    zones = [dict(name="所有交易日", **zst([i for i in range(n) if score[i] is not None]))]
    for t, nm in LEVELS: zones.append(dict(name=nm, **zst([i for i in range(n) if lvl(score[i]) == nm])))
    dd = dd_series(px); eps, last_hi = [], -999
    for i in range(n):
        if score[i] is not None and score[i] >= 90:
            if i - last_hi > 20:                     # 離開極度恐慌 20 天以上再進來,才算新的一次
                fut = px[i:i + 121]
                eps.append(dict(d=dates[i], score=score[i], px=round(px[i]), dd=r2(dd[i], 1), maxDrop=r2((min(fut) / px[i] - 1) * 100, 1) if len(fut) > 1 else None,
                                r20=r2(fw(i, 20), 1), r60=r2(fw(i, 60), 1), r120=r2(fw(i, 120), 1)))
            last_hi = i
    cs = []
    for c in comps:
        v, p = c["v"], c["p"]
        cs.append(dict(name=c["name"], desc=c["desc"], unit=c["unit"], value=r2(last(v)[0], c.get("nd", 1)), pct=r2(last(p)[0], 0),
                       prev=r2(p[-2], 0) if len(p) > 1 and p[-2] is not None else None, w1=r2(p[-6], 0) if len(p) > 5 and p[-6] is not None else None))
    k0 = next((i for i in range(n) if score[i] is not None), 0)
    return dict(name=name, idx=idx_name, date=dates[-1], score=score[-1], level=lvl(score[-1]), prev=ago(1), w1=ago(5), m1=ago(21), m3=ago(63),
                comps=cs, refs=[dict(name=a, value=b, unit=u, note=nt) for a, b, u, nt in refs], zones=zones, episodes=eps,
                series=dict(d=dates[k0:], px=[round(x, 2) for x in px[k0:]], f=score[k0:]), since=dates[k0])

# 台股:6 項計分
dd_tw = dd_series(TX)
tw_comps = [
    dict(name="加權指數 20 日實際波動", unit="%", desc="最近 20 天每天漲跌的劇烈程度（年化）；震得越兇越恐慌。", v=RV, p=exp_pct(RV)),
    dict(name="加權指數離近一年高點", unit="%", desc="收盤比近一年最高點低多少；跌越深越恐慌。", v=dd_tw, p=exp_pct([-x for x in dd_tw])),
    dict(name="估算融資維持率", unit="%", desc="融資戶抵押股票市值 ÷ 借款（證交所資料自算）；越低越接近追繳、越恐慌。", v=mKeep, p=[None if x is None else 100 - x for x in exp_pct(mKeep)]),
    dict(name="外資近 5 日買賣超", unit="億", nd=0, desc="外資最近 5 天現股買賣超合計；賣得越多越恐慌。", v=fi5, p=[None if x is None else 100 - x for x in exp_pct(fi5)]),
    dict(name="外資＋投信台指期淨未平倉", unit="口", nd=0, desc="外資加投信的期貨多單減空單（扣掉槓桿 ETF 對作後的真實淨空）；空單越多代表避險越重、越恐慌。", v=fiit, p=[None if x is None else 100 - x for x in exp_pct(fiit)]),
    dict(name="美股 VIX（前一晚）", unit="", desc="全球資金的恐慌溫度計；越高越恐慌。", v=vixUs, p=exp_pct(vixUs)),
]
BP = os.path.join(DATA, "breadth.json")             # 市場廣度(全部上市櫃普通股)
if os.path.exists(BP):
    br = {r[0]: r for r in json.load(open(BP))["rows"]}
    ld5 = [br.get(d, [None] * 4)[1] for d in D]; low5 = [br.get(d, [None] * 4)[2] for d in D]; a200 = [br.get(d, [None] * 4)[3] for d in D]
    if sum(x is not None for x in a200) > 200:
        tw_comps += [
            dict(name="跌停家數比例（5 日平均）", unit="%", nd=2, desc="上市櫃普通股中跌停的比例；越多代表多殺多、越恐慌。", v=ld5, p=exp_pct(ld5)),
            dict(name="創 52 週新低比例（5 日平均）", unit="%", desc="跌到一年來最低價的股票比例；越多代表殺盤擴散。", v=low5, p=exp_pct(low5)),
            dict(name="站上 200 日線比例", unit="%", desc="股價在 200 日均線之上的股票比例；越少代表普遍弱勢、越恐慌。", v=a200, p=[None if x is None else 100 - x for x in exp_pct(a200)]),
        ]
tw_refs = [("台指 VIX", r2(last(vixTw)[0]), "", "期交所只公開近幾個月，累積滿 1 年後再計入總分"),
           ("整戶擔保維持率", r2(last(keep)[0]), "%", "官方 2026/8 起才有資料"),
           ("追繳戶數", last(below)[0], "戶", "官方 2026/8 起才有資料")]
fear = {"tw": fear_block("台股", "加權指數", D, TX, tw_comps, tw_refs)}
# 美股 / 費半:實際波動、離一年高點、VIX 三項
vus_raw = json.load(open(os.path.join(DATA, "market", "raw_vixus.json")))
for key, sym, nm in (("us", "^GSPC", "標普500"), ("sox", "^SOX", "費城半導體")):
    rows = G["idx"].get(sym, {}).get("rows", [])
    if len(rows) < 300: continue
    gd, gp = [d for d, _ in rows], [v for _, v in rows]
    rv_g, dd_g, vx = rv_series(gp), dd_series(gp), ffill(gd, vus_raw)
    comps = [dict(name=f"{nm} 20 日實際波動", unit="%", desc="最近 20 天震盪幅度（年化）；越大越恐慌。", v=rv_g, p=exp_pct(rv_g)),
             dict(name=f"{nm}離近一年高點", unit="%", desc="比近一年最高點低多少；跌越深越恐慌。", v=dd_g, p=exp_pct([-x for x in dd_g])),
             dict(name="美股 VIX", unit="", desc="標普500 選擇權隱含的未來 30 天波動；越高越恐慌。", v=vx, p=exp_pct(vx))]
    fear[key] = fear_block("美股大盤" if key == "us" else "費城半導體", nm, gd, gp, comps)
# ---------- 9. 影響漲跌的關鍵數字(今天 vs 前一天,利多/利空 + 白話) ----------
def lastn(vals, k=0):
    xs = [(i, v) for i, v in enumerate(vals) if v is not None]
    return xs[-1 - k] if len(xs) > k else (None, None)
def f1(x, n=0, unit=""): return "—" if x is None else f"{x:+,.{n}f}{unit}" if unit in ("億", "口", "張", "點", "%") and x != 0 else f"{x:,.{n}f}{unit}"
drv = []
def D_(grp, name, val, chg, sig, why, date=None): drv.append(dict(grp=grp, name=name, val=val, chg=chg, sig=sig, why=why, date=date))
# 法人現貨
for key, nm, big in (("fi", "外資", 100), ("it", "投信", 20), ("dl", "自營商", 30)):
    i, v = lastn(col(key))
    if v is None: continue
    s_ = 1 if v > big * .1 else -1 if v < -big * .1 else 0
    D_("法人資金", f"{nm}買賣超", f"{v:+,.1f} 億", "", s_,
       (f"{nm}今天{'買超' if v > 0 else '賣超'} {abs(v):,.0f} 億。" + ("外資是台股最大資金，買超通常推升權值股、賣超壓抑指數。" if key == "fi" else
        "投信是國內基金，連續買超的股票常有表現；季底常有作帳。" if key == "it" else "自營商多為短線與避險，參考性較低。")), D[i])
i, v = lastn(ffi); _, v0 = lastn(ffi, 1)
if v is not None:
    ch = v - v0 if v0 is not None else None
    D_("期貨籌碼", "外資台指期淨未平倉", f"{v:+,.0f} 口", f"{ch:+,.0f} 口" if ch is not None else "", 1 if (ch or 0) > 3000 else -1 if (ch or 0) < -3000 else 0,
       f"外資期貨{'淨空' if v < 0 else '淨多'} {abs(v):,.0f} 口（扣掉投信槓桿 ETF 對作後真實淨空 {abs(fiit[i] or 0):,.0f} 口），比前一天{'空單增加' if (ch or 0) < 0 else '空單減少'} {abs(ch or 0):,.0f} 口。空單變多＝外資更看空或加強避險；空單大量回補常帶動急漲。", D[i])
i, v = lastn(col("fit")); _, v0 = lastn(col("fit"), 1)
if v is not None:
    D_("期貨籌碼", "投信台指期淨未平倉", f"{v:+,.0f} 口", f"{v - v0:+,.0f} 口" if v0 is not None else "", 0,
       "投信的期貨多單多半是 ETF（例如槓桿型）避險部位，看方向參考性較低。", D[i])
# 信用交易
i, v = lastn(mAmt); _, v0 = lastn(mAmt, 1)
if v is not None and v0:
    ch = v - v0; pct = ch / v0 * 100; up = (ret1[i] or 0) > 0
    sig = 0 if pct <= -2 else (-1 if (not up and ch > 0) else 0)
    D_("散戶信用", "融資餘額", f"{v:,.0f} 億", f"{ch:+,.0f} 億（{pct:+.1f}%）", sig,
       ("融資大減：散戶被迫斷頭或主動降槓桿，短線有賣壓，但籌碼會變乾淨。" if pct <= -2 else
        "指數跌、融資卻增加：散戶逢低攤平，套牢籌碼變多，反彈時容易遇到解套賣壓。" if (not up and ch > 0) else
        "融資增加、指數上漲：散戶追價，留意過熱。" if ch > 0 else "融資小幅減少，散戶槓桿下降。"), D[i])
sS = col("sShr"); i, v = lastn(sS); _, v0 = lastn(sS, 1)
if v is not None and v0:
    D_("散戶信用", "融券餘額", f"{v:,.0f} 張", f"{v - v0:+,.0f} 張", 0, "融券＝借股票來賣（看空）。融券增加代表空方加碼，但之後回補時也會變成買盤（軋空燃料）。", D[i])
i, v = lastn(keep)
if v is not None:
    D_("散戶信用", "整戶擔保維持率", f"{v:.2f}%", "", 1 if v >= 170 else -1 if v < 160 else 0,
       f"低於 130% 會被追繳。{'已跌破 160% 危險線，斷頭賣壓明顯。' if v < 160 else '在警戒區。' if v < 170 else '在安全範圍。'}", D[i])
i, v = lastn(below)
if v is not None:
    D_("散戶信用", "追繳戶數", f"{v:,.0f} 戶", "", -1 if v >= 700 else 0 if v >= 300 else 1,
       f"{'斷頭潮等級：' if v >= 2000 else '異常偏高：' if v >= 700 else ''}被追繳的帳戶若 2 天內沒補錢就會被強制賣出，短線形成賣壓；但斷頭出清後常接近短期底部。", D[i])
# 市場內部
txv = col("txV"); i, v = lastn(txv)
if v:
    avg = st.mean([x for x in txv[max(0, i - 20):i] if x]); r = v / avg; up = (ret1[i] or 0) > 0
    D_("市場內部", "成交量", f"{v:,.0f} 億", f"{r:.2f} 倍均量", (1 if up else -1) if r > 1.2 else 0,
       f"今天成交量是近 20 日平均的 {r:.2f} 倍。" + ("價漲量增：上漲有人跟，比較健康。" if up and r > 1.2 else "價跌量增：急著賣的人多，恐慌或斷頭賣壓。" if (not up) and r > 1.2 else "量能普通。"), D[i])
BPJ = os.path.join(DATA, "breadth.json")
if os.path.exists(BPJ):
    bj = json.load(open(BPJ)); bc = {c: k for k, c in enumerate(bj["cols"])}
    br_rows = [r_ for r_ in bj["rows"] if len(r_) >= len(bj["cols"])]
    if br_rows:
        b = br_rows[-1]
        D_("市場內部", "上漲／下跌家數", f"{b[bc['adv']]:,} ／ {b[bc['dec']]:,}", "", 1 if b[bc['adv']] > b[bc['dec']] * 1.2 else -1 if b[bc['dec']] > b[bc['adv']] * 1.2 else 0,
           "上市櫃普通股中上漲和下跌的家數；指數漲但下跌家數多，代表只有少數權值股在撐。", b[0])
        D_("市場內部", "漲停／跌停家數", f"{b[bc['lu']]:,} ／ {b[bc['ld']]:,}", "", -1 if b[bc['ld']] > max(20, b[bc['lu']] * 2) else 1 if b[bc['lu']] > max(20, b[bc['ld']] * 2) else 0,
           "跌停家數暴增＝多殺多、恐慌賣壓；漲停家數多＝資金積極追價。", b[0])
        D_("市場內部", "創 52 週新低家數", f"{b[bc['lowN']]:,} 家", f"5 日平均占 {b[bc['low5']]}%", -1 if (b[bc['low5']] or 0) > 10 else 0,
           "跌到一年最低價的股票數；越多代表殺盤擴散到大部分股票。", b[0])
        D_("市場內部", "站上 200 日線比例", f"{b[bc['a200']]}%", "", 1 if (b[bc['a200']] or 0) >= 60 else -1 if (b[bc['a200']] or 0) < 30 else 0,
           "股價在 200 日均線（長期趨勢）之上的股票比例；低於 20% 屬普遍弱勢，歷史上常出現在恐慌末段。", b[0])
# 情緒
for vals, nm in ((vixTw, "台指 VIX"), (vixUs, "美股 VIX")):
    i, v = lastn(vals); _, v0 = lastn(vals, 1)
    if v is None: continue
    D_("市場情緒", nm, f"{v:.2f}", f"{v - v0:+.2f}" if v0 else "", -1 if v >= 30 else 1 if v < 18 else 0,
       f"{'極度恐慌' if v >= 40 else '恐慌' if v >= 30 else '緊張' if v >= 20 else '平靜'}。VIX 越高代表市場預期震盪越大；短線不利，但極端高點常接近底部。", D[i])
ft = fear.get("tw")
if ft and ft.get("score") is not None: D_("市場情緒", "台股恐慌度", f"{ft['score']}（{ft['level']}）", f"{ft['score'] - ft['prev']:+d}" if ft.get("prev") is not None else "", -1 if (ft["score"] or 0) >= 75 else 1 if (ft["score"] or 0) < 25 else 0,
          "綜合多項指標的 0～100 分；分數高代表大家很怕，短線賣壓重，但歷史上極度恐慌後半年的表現常比平常好。", ft["date"])
# 國際
def gchg(sym, src=None):
    rows = (src or G["idx"]).get(sym, {}).get("rows", [])
    return (rows[-1][0], rows[-1][1], (rows[-1][1] / rows[-2][1] - 1) * 100) if len(rows) > 1 else (None, None, None)
for sym, nm, why in (("^SOX", "費城半導體（前一晚）", "台股權值以半導體為主，費半前一晚漲跌常直接影響台積電等開盤方向。"),
                     ("^IXIC", "那斯達克（前一晚）", "美國科技股指標，影響台股電子股情緒。"),
                     ("^GSPC", "標普500（前一晚）", "美國大盤，代表全球風險情緒。"),
                     ("^N225", "日經225（今天）", "日本股市，和台股同屬亞洲科技供應鏈，相關性最高。"),
                     ("^KS11", "韓國 KOSPI（今天）", "韓國以半導體、電子為主，和台股走勢高度相關。")):
    d_, v, c = gchg(sym)
    if v: D_("國際股市", nm, f"{v:,.0f}", f"{c:+.2f}%", 1 if c > .5 else -1 if c < -.5 else 0, why, d_)
MAC = G.get("macro", {})
d_, v, c = gchg("TWD=X", MAC)
if v: D_("匯率利率", "美元兌台幣", f"{v:.3f}", f"{c:+.2f}%", -1 if c > .15 else 1 if c < -.15 else 0,
         f"數字變大＝台幣貶值。{'台幣貶值通常代表外資匯出、賣台股。' if c > 0 else '台幣升值通常代表外資匯入、有利台股。'}", d_)
rows = MAC.get("^TNX", {}).get("rows", [])
if len(rows) > 1:
    v, ch = rows[-1][1], rows[-1][1] - rows[-2][1]
    D_("匯率利率", "美國 10 年期公債殖利率", f"{v:.2f}%", f"{ch * 100:+.0f} 個基點", -1 if ch > .04 else 1 if ch < -.04 else 0,
       "美債殖利率上升＝資金成本變高，會壓低高本益比科技股的評價；下降則有利成長股。", rows[-1][0])
d_, v, c = gchg("CL=F", MAC)
if v: D_("匯率利率", "西德州原油", f"{v:.2f} 美元", f"{c:+.2f}%", -1 if c > 3 else 0,
         "油價大漲會推升通膨、讓央行更難降息，對股市不利；對塑化、航運等族群影響較大。", d_)
# 技術面
t = tech_view
D_("技術面", "均線位置", f"{fmt_ma(t)}" if False else f"月 {t['ma20']:,.0f}／季 {t['ma60']:,.0f}／年 {t['ma240']:,.0f}", f"離季線 {t['bias60']:+.1f}%",
   -1 if t["price"] < t["ma60"] else 1, "指數在均線之上＝趨勢向上；跌破季線＝中期轉弱、跌破年線＝長期轉空。乖離太大時容易出現反彈或拉回。", t["date"])
D_("技術面", "RSI（14 日）", f"{t['rsi']}", "", 1 if t["rsi"] < 30 else -1 if t["rsi"] > 70 else 0,
   "低於 30＝跌多了（超賣），短線有反彈機會；高於 70＝漲多了（超買）。這是反向訊號，不代表趨勢翻轉。", t["date"])
D_("技術面", "KD", f"K {t['k']}／D {t['d']}", "", 1 if t["k"] > t["d"] else -1, "K 在 D 之上＝短線轉強；K 低於 20 是超賣區。", t["date"])
D_("技術面", "MACD 動能", "轉強" if t["macdUp"] else "轉弱", "", 1 if t["macdUp"] else -1, "MACD 柱狀體往上＝下跌（或上漲）力道在改善；往下＝動能轉弱。", t["date"])
drv_sum = dict(up=sum(1 for x in drv if x["sig"] > 0), dn=sum(1 for x in drv if x["sig"] < 0), flat=sum(1 for x in drv if x["sig"] == 0))
out = dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), date=D[-1], cards=cards, tech=tech_view,
           base={str(h): base[h] for h in base}, events=events, corr=corr_fwd, global_=glob, quads=quads,
           forecast=fc, score=score, stance=stance, components=comp,
           support=[dict(name=n, v=v) for n, v in sup], resist=[dict(name=n, v=v) for n, v in res], summary=say, fear=fear, drivers=drv, drvSum=drv_sum)
json.dump(out, open(os.path.join(DATA, "market_analysis.json"), "w"), ensure_ascii=False, separators=(",", ":"))
print("market_analysis.json OK", D[-1], "分數", score, stance)
print("\n".join(say))
