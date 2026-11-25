"""ETF 估價(便宜價／合理價／昂貴價＋股價位階) -> data/etf_val.json
讀 data/summary.json、data/prices/<id>.json([日期, 開, 高, 低, 收, 量])、data/dividends/<id>.json

兩種方法,都是「跟這檔 ETF 自己過去比」:
  y 殖利率法(高股息、債券、不動產、金融、平衡型,且有 2 年以上配息):
      每天算「近一年配息 ÷ 當天收盤」= 當時殖利率,取近 5 年的分布
      便宜價 = 近一年配息 ÷ 歷史高殖利率(80% 分位)
      合理價 = 近一年配息 ÷ 歷史中位數殖利率
      昂貴價 = 近一年配息 ÷ 歷史低殖利率(20% 分位)
  t 成長軌道法(市值型、科技、主題、ESG,或配息資料不夠的):
      用還原息值的收盤價,對近 5 年畫一條「平均成長軌道」(對數股價的直線回歸＝固定年增率)
      看每天股價高於/低於軌道多少,取分布
      便宜價 = 今天的軌道價 × 低於軌道的 20% 分位
      合理價 = 今天的軌道價(× 中位數,約等於軌道本身)
      昂貴價 = 今天的軌道價 × 高於軌道的 80% 分位
      (曾試年線乖離法:多頭市場股價大多在年線上,便宜價會高於年線,幾乎全部判成便宜,不用)
  槓桿反向、原物料期貨:不估價(價格會耗損、沒有合理價的概念)
  上市不到約 2 年(480 個交易日)的:資料不足,不估價
區間判定(和個股一樣):≤便宜價=便宜、≤合理價=合理、≤昂貴價=偏貴、>昂貴價=昂貴
位階 0~100:便宜價=20、合理價=50、昂貴價=80,中間線性;便宜價×0.8 以下=0、昂貴價×1.2 以上=100
"""
import json, os, math, datetime as dt

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
INCOME = {"高股息", "債券", "不動產", "金融", "平衡型"}
SKIP = {"槓桿反向", "原物料期貨"}
YEARS = 5
MIN_DAYS = 480


def load(p, default=None):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return default


def pct(xs, q):
    xs = sorted(xs)
    if not xs: return None
    k = (len(xs) - 1) * q; f = math.floor(k); c = math.ceil(k)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def d(s): return dt.date.fromisoformat(s[:10])


def zone(px, c, f, e):
    return "便宜" if px <= c else "合理" if px <= f else "偏貴" if px <= e else "昂貴"


def pos(px, c, f, e):
    pts = [(c * .8, 0), (c, 20), (f, 50), (e, 80), (e * 1.2, 100)]
    if px <= pts[0][0]: return 0
    if px >= pts[-1][0]: return 100
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= px <= x1: return round(y0 + (y1 - y0) * (px - x0) / (x1 - x0) if x1 > x0 else y1)
    return None


def ttm_at(D, t, k):
    """t 當天往回最近 k 次配息(只算 400 天內的,避免除息日飄移時一年算到 5 次)"""
    xs = [cash for ex, cash in D if t - dt.timedelta(days=400) < ex <= t]
    return sum(xs[-k:]) if xs else 0


def yield_method(P, D, ttm, k):
    """P: [(date, close)], D: [(exdate, cash)] -> (c, f, e, hi, mid, lo, n)"""
    if not D or ttm <= 0: return None
    first_ex = D[0][0]
    if (P[-1][0] - first_ex).days < 730: return None          # 配息紀錄不到 2 年
    start = P[-1][0] - dt.timedelta(days=365 * YEARS)
    ys = []
    for t, c in P:
        if t < start or c <= 0: continue
        if (t - first_ex).days < 365: continue                   # 第一年的近一年配息還不完整
        tt = ttm_at(D, t, k)
        if tt > 0: ys.append(tt / c)
    if len(ys) < 250: return None
    hi, mid, lo = pct(ys, .8), pct(ys, .5), pct(ys, .2)
    if not (hi and mid and lo) or lo <= 0: return None
    return ttm / hi, ttm / mid, ttm / lo, hi, mid, lo, len(ys)


def adj_closes(P, D):
    """還原息值:除息日之前的價格乘上 (前收-股利)/前收"""
    n = len(P); closes = [c for _, c in P]; fac = [1.0] * n
    for ex, cash in D:
        k = next((i for i, (t, _) in enumerate(P) if t >= ex), None)
        if not k or k <= 0: continue
        prev = closes[k - 1]
        if prev <= 0 or cash >= prev: continue
        f = (prev - cash) / prev
        for i in range(k): fac[i] *= f
    return [c * f for c, f in zip(closes, fac)]


def trend_method(P, D):
    """近 5 年對數股價直線回歸 = 平均成長軌道;股價相對軌道的分布取 20/50/80% 分位"""
    if len(P) < MIN_DAYS: return None
    adj = adj_closes(P, D)
    start = P[-1][0] - dt.timedelta(days=365 * YEARS)
    idx = [i for i in range(len(P)) if P[i][0] >= start and adj[i] > 0]
    if len(idx) < MIN_DAYS: return None
    xs = [(P[i][0] - P[idx[0]][0]).days for i in idx]; ys = [math.log(adj[i]) for i in idx]
    m = len(xs); mx = sum(xs) / m; my = sum(ys) / m
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0: return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx; a = my - b * mx
    res = [y - (a + b * x) for x, y in zip(xs, ys)]
    lo, mid, hi = pct(res, .2), pct(res, .5), pct(res, .8)
    tr = math.exp(a + b * xs[-1])
    g = math.exp(b * 365) - 1                                    # 軌道的年增率
    return tr * math.exp(lo), tr * math.exp(mid), tr * math.exp(hi), lo, mid, hi, tr, g, m


def trim_jumps(P):
    """價格若有沒還原的分割/合併(一天跳 >60% 或腰斬),只用跳動之後的資料"""
    cut = 0
    for i in range(1, len(P)):
        a, b = P[i - 1][1], P[i][1]
        if a > 0 and b > 0 and (b / a < .62 or b / a > 1.6): cut = i
    return P[cut:]


def main():
    S = load(os.path.join(DATA, "summary.json"), {}) or {}
    SPL = load(os.path.join(DATA, "splits.json"), {}) or {}
    out, cnt = {}, {"y": 0, "t": 0, "skip": 0, "few": 0}
    for e in S.get("etfs", []):
        sid, cat = e.get("id"), e.get("category")
        if not sid: continue
        if cat in SKIP: out[sid] = {"na": "槓桿反向、期貨型 ETF 價格會耗損，不適用估價"}; cnt["skip"] += 1; continue
        P = trim_jumps([(d(r[0]), float(r[4])) for r in (load(os.path.join(DATA, "prices", sid + ".json"), []) or []) if r and r[4]])
        D = sorted((d(x["ex"]), float(x["cash"])) for x in (load(os.path.join(DATA, "dividends", sid + ".json"), []) or [])
                   if x.get("ex") and x.get("cash"))
        for sd, ratio in SPL.get(sid, []):                       # 價格已還原分割,分割前的配息也要同比例換算
            D = [(ex, c * ratio if ex < d(sd) else c) for ex, c in D]
        if len(P) < MIN_DAYS: out[sid] = {"na": "上市未滿約 2 年，歷史資料不夠估價"}; cnt["few"] += 1; continue
        px, last = P[-1][1], P[-1][0]
        D = [x for x in D if x[0] <= last]
        k = int(e.get("perYear") or 0) or max(1, sum(1 for ex, _ in D if last - dt.timedelta(days=365) < ex <= last))
        ttm = ttm_at(D, last, k)
        yrs = {}
        for ex, c in D: yrs[ex.year] = yrs.get(ex.year, 0) + c
        full = [yrs[y] for y in (last.year - 1, last.year - 2, last.year - 3) if y in yrs and y > D[0][0].year] if D else []
        avg3 = sum(full) / len(full) if full else None
        jump = bool(avg3 and ttm > avg3 * 1.25)
        base_d = (ttm + avg3) / 2 if jump else ttm               # 近一年配息暴增時,和過去平均取中間,比較保守
        yy = {k: v for k, v in (e.get("yearYields") or {}).items() if k.isdigit() and int(k) < last.year and v.get("yld")}
        ya = round(sum(v["yld"] for v in yy.values()) / len(yy), 2) if yy else None
        base = {"px": px, "dt": last.isoformat(), "y": e.get("ttmYield"), "ya": ya, "yn": len(yy)}
        r = yield_method(P, D, base_d, k) if cat in INCOME else None
        if r:
            c, f, x, hi, mid, lo, n = r
            out[sid] = {**base, "m": "y", "v": [round(c, 2), round(f, 2), round(x, 2)], "d": round(base_d, 3), "tt": round(ttm, 3),
                        "a3": round(avg3, 3) if avg3 else None, "j": 1 if jump else 0,
                        "k": [round(hi * 100, 2), round(mid * 100, 2), round(lo * 100, 2)], "n": n}
            cnt["y"] += 1
        else:
            r = trend_method(P, D)
            if not r: out[sid] = {"na": "歷史資料不夠估價"}; cnt["few"] += 1; continue
            c, f, x, lo, mid, hi, tr, g, n = r
            if not (c < f < x) or x / c < 1.02: out[sid] = {"na": "價格波動太小，估價區間沒有意義"}; cnt["few"] += 1; continue
            out[sid] = {**base, "m": "t", "v": [round(c, 2), round(f, 2), round(x, 2)], "tr": round(tr, 2), "g": round(g * 100, 1),
                        "k": [round((math.exp(lo) - 1) * 100, 1), round((math.exp(mid) - 1) * 100, 1), round((math.exp(hi) - 1) * 100, 1)], "n": n}
            cnt["t"] += 1
        o = out[sid]; c, f, x = o["v"]
        o["z"] = zone(px, c, f, x); o["p"] = pos(px, c, f, x)
    res = {"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "count": cnt,
           "note": "y=殖利率法(配息基準d÷自己近5年殖利率的80/50/20%分位;d=近一年配息tt,若tt>過去3年平均a3的1.25倍則取兩者平均,j=1) t=成長軌道法(近5年還原息值股價的對數直線回歸=軌道tr,年增率g%;v=軌道×自己偏離軌道的20/50/80%分位,k=偏離%);v=[便宜,合理,昂貴] z=區間 p=位階0~100 y=近一年殖利率 ya=過去完整年度平均殖利率 yn=年數",
           "etfs": out}
    with open(os.path.join(DATA, "etf_val.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    print("etf_val:", cnt)


if __name__ == "__main__":
    main()
