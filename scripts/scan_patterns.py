"""線型選股:全部上市櫃普通股,用近 300 個交易日收盤價找線型 -> data/patterns.json
資料:data/breadth/raw/*.json(fetch_breadth.py 下載的全市場每日收盤)
型態:W底/M頭/頭肩底/頭肩頂(成形中、剛突破/跌破頸線)、三角收斂、箱型整理、突破下降趨勢線、跌破上升趨勢線、
      多頭排列/空頭排列/均線糾結、葛蘭碧買點①/賣點①、站上/跌破季線
規則與網頁上的線型分析相同(以收盤價計算,較保守)
"""
import json, os, sys, datetime as dt, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; RAW = os.path.join(DATA, "breadth", "raw")

files = sorted(f for f in os.listdir(RAW) if f.endswith(".json"))[-300:]
days = [f[:10] for f in files]
series = {}
for k, f in enumerate(files):
    for code, c in json.load(open(os.path.join(RAW, f)))["c"].items():
        series.setdefault(code, {})[k] = c
N = len(days)
try:
    names = {r["stock_id"]: r["stock_name"] for r in fh.finmind("TaiwanStockInfo", "", "")}
except Exception: names = {}

def sma(c, n, i): return sum(c[i - n + 1:i + 1]) / n if i >= n - 1 else None
def pivots(c, thr):
    P, d, hi, lo, ext = [], 0, 0, 0, 0
    for i in range(1, len(c)):
        if d == 0:
            if c[i] > c[hi]: hi = i
            if c[i] < c[lo]: lo = i
            if c[hi] / c[lo] - 1 > thr:
                if hi > lo: P.append((lo, c[lo], "L")); d, ext = 1, hi
                else: P.append((hi, c[hi], "H")); d, ext = -1, lo
        elif d == 1:
            if c[i] >= c[ext]: ext = i
            elif c[ext] / c[i] - 1 > thr: P.append((ext, c[ext], "H")); d, ext = -1, i
        else:
            if c[i] <= c[ext]: ext = i
            elif c[i] / c[ext] - 1 > thr: P.append((ext, c[ext], "L")); d, ext = 1, i
    return P
near = lambda a, b, t=.035: abs(a - b) / min(a, b) < t
def line_at(a, b, i): return a[1] + (b[1] - a[1]) * (i - a[0]) / (b[0] - a[0])

def scan(c):
    n = len(c); last = n - 1; px = c[last]; out = []
    rets = [abs(c[i] / c[i - 1] - 1) for i in range(n - 20, n)]
    thr = min(.12, max(.04, st.mean(rets) * 3.2))
    P = pivots(c, thr); T = P[-5:]
    broke = lambda lvl, up: any((c[j] > lvl) if up else (c[j] < lvl) for j in range(last - 4, last + 1)) and ((c[last - 5] <= lvl) if up else (c[last - 5] >= lvl))
    # 型態
    if len(T) >= 3:
        a, b, d_ = T[-3:]
        if a[2] == "L" and b[2] == "H" and d_[2] == "L" and near(a[1], d_[1]):
            h = b[1] - min(a[1], d_[1])
            if px > b[1]: out.append(("w_up", dict(neck=b[1], target=b[1] + h, fresh=broke(b[1], True))))
            elif px > d_[1]: out.append(("w_form", dict(neck=b[1], target=b[1] + h)))
        if a[2] == "H" and b[2] == "L" and d_[2] == "H" and near(a[1], d_[1]):
            h = max(a[1], d_[1]) - b[1]
            if px < b[1]: out.append(("m_dn", dict(neck=b[1], target=b[1] - h, fresh=broke(b[1], False))))
            elif px < d_[1]: out.append(("m_form", dict(neck=b[1], target=b[1] - h)))
    if len(T) == 5:
        a, b, d_, e, f = T
        if a[2] == "L" and d_[1] < a[1] and d_[1] < f[1] and near(a[1], f[1], .06):
            neck = (b[1] + e[1]) / 2; h = neck - d_[1]
            out.append(("hs_bot_up" if px > neck else "hs_bot_form", dict(neck=neck, target=neck + h)))
        if a[2] == "H" and d_[1] > a[1] and d_[1] > f[1] and near(a[1], f[1], .06):
            neck = (b[1] + e[1]) / 2; h = d_[1] - neck
            out.append(("hs_top_dn" if px < neck else "hs_top_form", dict(neck=neck, target=neck - h)))
    hs = [p for p in T if p[2] == "H"][-2:]; ls = [p for p in T if p[2] == "L"][-2:]
    if len(hs) == 2 and len(ls) == 2:
        if hs[1][1] < hs[0][1] and ls[1][1] > ls[0][1]:
            up, lo = line_at(hs[0], hs[1], last), line_at(ls[0], ls[1], last)
            if lo < px < up: out.append(("tri", dict(upper=up, lower=lo, width=(up - lo) / px * 100)))
        elif near(hs[0][1], hs[1][1]) and near(ls[0][1], ls[1][1]):
            top, bot = max(hs[0][1], hs[1][1]), min(ls[0][1], ls[1][1])
            if bot <= px <= top: out.append(("box", dict(top=top, bot=bot)))
    # 趨勢線
    Hs = [p for p in P if p[2] == "H"]; Ls = [p for p in P if p[2] == "L"]
    if len(Hs) >= 2 and Hs[-1][1] < Hs[-2][1]:
        v = line_at(Hs[-2], Hs[-1], last); v5 = line_at(Hs[-2], Hs[-1], last - 5)
        if px > v and c[last - 5] <= v5: out.append(("tl_up", dict(line=v)))
    if len(Ls) >= 2 and Ls[-1][1] > Ls[-2][1]:
        v = line_at(Ls[-2], Ls[-1], last); v5 = line_at(Ls[-2], Ls[-1], last - 5)
        if px < v and c[last - 5] >= v5: out.append(("tl_dn", dict(line=v)))
    # 均線
    m5, m10, m20, m60 = (sma(c, k, last) for k in (5, 10, 20, 60))
    if m60:
        if m5 > m10 > m20 > m60: out.append(("ma_bull", dict(ma20=m20, ma60=m60)))
        elif m5 < m10 < m20 < m60: out.append(("ma_bear", dict(ma20=m20, ma60=m60)))
        elif (max(m5, m10, m20, m60) - min(m5, m10, m20, m60)) / px < .02: out.append(("ma_tangle", dict(ma60=m60)))
        s60 = (m60 - sma(c, 60, last - 5)) / m60 * 100
        if px > m60 and c[last - 5] < sma(c, 60, last - 5) and s60 >= -0.1: out.append(("g_buy1", dict(ma60=m60, slope=s60)))
        if px < m60 and c[last - 5] > sma(c, 60, last - 5) and s60 <= 0.1: out.append(("g_sell1", dict(ma60=m60, slope=s60)))
        if px < m60 and s60 < 0 and px / m60 - 1 < -.15: out.append(("g_buy4", dict(ma60=m60, bias=(px / m60 - 1) * 100)))
    return out

LABEL = {
    "w_up": ("W 底突破頸線", 1), "w_form": ("W 底成形中", 0), "m_dn": ("M 頭跌破頸線", -1), "m_form": ("M 頭成形中", 0),
    "hs_bot_up": ("頭肩底突破頸線", 1), "hs_bot_form": ("頭肩底成形中", 0), "hs_top_dn": ("頭肩頂跌破頸線", -1), "hs_top_form": ("頭肩頂成形中", 0),
    "tri": ("三角收斂", 0), "box": ("箱型整理", 0), "tl_up": ("突破下降趨勢線", 1), "tl_dn": ("跌破上升趨勢線", -1),
    "ma_bull": ("均線多頭排列", 1), "ma_bear": ("均線空頭排列", -1), "ma_tangle": ("均線糾結（變盤前兆）", 0),
    "g_buy1": ("葛蘭碧買點①：突破季線", 1), "g_sell1": ("葛蘭碧賣點①：跌破季線", -1), "g_buy4": ("葛蘭碧買點④：負乖離過大", 1),
}
groups = {k: [] for k in LABEL}
scanned = 0
for code, m in series.items():
    if len(m) < 200 or (N - 1) not in m: continue
    ks = sorted(m); c = [m[k] for k in ks]
    if c[-1] < 10: continue                               # 雞蛋水餃股不列
    scanned += 1
    for key, info in scan(c):
        r = dict(id=code, name=names.get(code, ""), px=c[-1], chg=round((c[-1] / c[-2] - 1) * 100, 2), **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in info.items()})
        groups[key].append(r)
for k, L in groups.items():                                # 排序:剛突破/跌破優先,其次離頸線近
    L.sort(key=lambda r: (not r.get("fresh", False), abs(r["px"] / r.get("neck", r.get("line", r.get("ma60", r["px"])) or r["px"]) - 1)))
out = dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), date=days[-1], scanned=scanned,
           labels={k: dict(name=v[0], sig=v[1], n=len(groups[k])) for k, v in LABEL.items()},
           groups={k: L[:150] for k, L in groups.items()})
fh.save(os.path.join(DATA, "patterns.json"), out)
print(f"patterns.json {days[-1]}:掃描 {scanned} 檔;" + "、".join(f"{v[0]} {len(groups[k])}" for k, v in LABEL.items()))
