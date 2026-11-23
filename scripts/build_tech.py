"""日線技術面(買點時機)-> data/tech.json
全部上市櫃普通股,用 data/breadth/raw/*.json(fetch_breadth.py 下載的每日收盤,雲端快取)
每檔算:均線(5/10/20/60/120)、排列、RSI14、MACD(12,26,9)、20 日支撐/壓力、5/20 日漲跌、技術分數與「買點訊號」
訊號(以收盤價判斷,偏保守):
  down  📉 下跌中        股價在月線下、月線下彎,且近 3 日創 20 日新低或 MACD 柱狀體持續轉弱 → 勿接刀
  base  ⏳ 打底中        仍在月線下,但跌勢減緩(MACD 柱狀體回升或 RSI 低於 35 後止跌)→ 等止跌確認
  turn  ✅ 轉強          近 5 日站回月線,或近 3 日 MACD 黃金交叉且站上 10 日線 → 可分批進場
  hot   🔥 偏熱          多頭排列但離月線超過 10% 或 RSI>75 → 等拉回
  up    👍 多頭          多頭排列 / 股價在月線上且月線上揚
  side  ➖ 盤整          其他
"""
import json, os, sys, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; RAW = os.path.join(DATA, "breadth", "raw")
SIG = {"down": "📉 下跌中", "base": "⏳ 打底中", "turn": "✅ 轉強", "hot": "🔥 偏熱", "up": "👍 多頭", "side": "➖ 盤整"}

def sma(c, n, i=None):
    i = len(c) - 1 if i is None else i
    return sum(c[i - n + 1:i + 1]) / n if i >= n - 1 else None
def ema_series(c, n):
    k, out = 2 / (n + 1), []
    for i, v in enumerate(c): out.append(v if i == 0 else v * k + out[-1] * (1 - k))
    return out
def rsi(c, n=14):
    if len(c) < n + 1: return None
    g = l = 0
    for i in range(1, n + 1): d = c[i] - c[i - 1]; g += max(d, 0); l += max(-d, 0)
    g /= n; l /= n
    for i in range(n + 1, len(c)): d = c[i] - c[i - 1]; g = (g * (n - 1) + max(d, 0)) / n; l = (l * (n - 1) + max(-d, 0)) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)

def analyze(c):
    if len(c) < 70: return None
    px = c[-1]; m5, m10, m20, m60 = sma(c, 5), sma(c, 10), sma(c, 20), sma(c, 60); m120 = sma(c, 120)
    m20p = sma(c, 20, len(c) - 6)                                    # 5 日前的月線(看斜率)
    e12, e26 = ema_series(c, 12), ema_series(c, 26); dif = [a - b for a, b in zip(e12, e26)]; dea = ema_series(dif, 9); hist = [a - b for a, b in zip(dif, dea)]
    r = rsi(c[-120:]); lo20, hi20 = min(c[-20:]), max(c[-20:])
    newlow = min(c[-3:]) <= min(c[-20:]) * 1.0001
    gold = any(hist[-k - 1] <= 0 < hist[-k] for k in range(1, 4)); dead = any(hist[-k - 1] >= 0 > hist[-k] for k in range(1, 4))
    cross_up = any(c[-k - 1] < sma(c, 20, len(c) - k - 1) <= c[-k] for k in range(1, 6))
    bull = m5 > m10 > m20 > m60; bear = m5 < m10 < m20 < m60
    rising = m20 > m20p; dist = (px / m20 - 1) * 100
    hup = hist[-1] > hist[-2] > hist[-3]; hdn = hist[-1] < hist[-2] < hist[-3]
    if px < m20 and not rising and (newlow or hdn): s = "down"
    elif (cross_up and px >= m20) or (gold and px > m10): s = "turn"
    elif bull and (dist > 10 or (r or 0) > 75): s = "hot"
    elif bull or (px > m20 and rising): s = "up"
    elif px < m20 and (hup or ((r or 50) < 35 and c[-1] >= c[-2])): s = "base"
    else: s = "side"
    sc = (15 if px > m20 else 0) + (15 if rising else 0) + (10 if px > m60 else 0) + (10 if m5 > m20 else 0) + (10 if hist[-1] > 0 else 0) \
         + (10 if hist[-1] > hist[-2] else 0) + (10 if r is not None and 40 <= r <= 70 else 5 if r is not None and r < 30 else 0) + (10 if not newlow else 0) + (10 if px >= c[-6] else 0)
    trend = "多頭排列" if bull else "空頭排列" if bear else "均線糾結" if max(m5, m10, m20) / min(m5, m10, m20) < 1.015 else "整理"
    R = lambda x, n=2: None if x is None else round(x, n)
    return [sc, s, trend, R(r, 0), R(dist, 1), R((px / c[-6] - 1) * 100, 1), R((px / c[-21] - 1) * 100, 1), R(m20), R(m60), R(lo20), R(hi20),
            "gold" if gold else "dead" if dead else "", R(m120)]

def main():
    if not os.path.isdir(RAW): print("沒有 breadth raw,略過 tech.json"); return
    files = sorted(f for f in os.listdir(RAW) if f.endswith(".json"))[-300:]
    if len(files) < 70: print("breadth raw 天數不足", len(files)); return
    series = {}
    for k, f in enumerate(files):
        for code, v in json.load(open(os.path.join(RAW, f)))["c"].items(): series.setdefault(code, []).append((k, v))
    last = len(files) - 1; out = {}
    for code, pts in series.items():
        if pts[-1][0] < last - 2: continue                            # 近 3 日沒有成交(停牌)不算
        c = [v for _, v in pts]
        a = analyze(c)
        if a: out[code] = a
    cnt = {k: sum(1 for v in out.values() if v[1] == k) for k in SIG}
    fh.save(os.path.join(DATA, "tech.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), d=files[-1][:10], sig=SIG,
            cols=["技術分數", "訊號", "均線", "RSI", "離月線%", "5日%", "20日%", "月線", "季線", "20日支撐", "20日壓力", "MACD交叉", "半年線"], s=out, cnt=cnt,
            note="以每日收盤價計算;月線=20日均線、季線=60日均線、半年線=120日均線;支撐/壓力=近20日最低/最高收盤"))
    print("tech.json:", len(out), "檔", "、".join(f"{SIG[k]} {v}" for k, v in cnt.items()))

if __name__ == "__main__":
    main()
