"""個股填息分析 -> data/fill.json
資料:stock_div.json 的 past(除權息紀錄,含除息前一天收盤 before)+ data/breadth/raw(近 300 個交易日全市場收盤,雲端快取)
填息＝除息後收盤價回到 ≥ 除息前一天收盤價;天數＝從除息日起算第幾個交易日填息(當天填息＝1)
每檔保留最近 5 次;另算平均填息天數、填息率
"""
import json, os, sys, datetime as dt, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; RAW = os.path.join(DATA, "breadth", "raw")

def analyze(days, closes, ev):
    """days: 交易日清單;closes: {日期: 收盤};ev: {d, before, val} -> [除息日, 股利, 除息前收盤, 填息天數或 None, 已過天數]"""
    if ev["d"] not in days or not ev.get("before"): return None
    i = days.index(ev["d"]); n = 0
    for j in range(i, len(days)):
        c = closes.get(days[j])
        if c is None: continue
        n += 1
        if c >= ev["before"]: return [ev["d"], ev.get("val"), ev["before"], n, n]
    return [ev["d"], ev.get("val"), ev["before"], None, n]

def main():
    if not os.path.isdir(RAW): print("沒有 breadth raw,略過 fill.json"); return
    files = sorted(f for f in os.listdir(RAW) if f.endswith(".json"))
    if len(files) < 30: print("breadth raw 天數不足"); return
    days = [f[:10] for f in files]; series = {}
    for f in files:
        for c, v in json.load(open(os.path.join(RAW, f)))["c"].items(): series.setdefault(c, {})[f[:10]] = v
    past = (json.load(open(os.path.join(DATA, "stock_div.json"))) or {}).get("past", [])
    out, stat = {}, {}
    for ev in sorted(past, key=lambda e: e["d"]):
        if "息" not in (ev.get("k") or "") or ev["c"] not in series: continue
        r = analyze(days, series[ev["c"]], ev)
        if r: out.setdefault(ev["c"], []).append(r)
    for c, L in out.items():
        out[c] = L[-5:]
        done = [x[3] for x in L if x[3] is not None]
        stat[c] = [round(st.mean(done), 1) if done else None, round(len(done) / len(L) * 100), len(L)]
    fh.save(os.path.join(DATA, "fill.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), since=days[0], s=out, stat=stat,
            cols=["除息日", "現金股利", "除息前收盤", "填息天數(交易日,未填息為 null)", "已過交易日"], note="填息＝除息後收盤價回到除息前一天的收盤價；只統計近一年多的除息紀錄"))
    print("fill.json:", len(out), "檔;平均填息天數中位數", st.median([v[0] for v in stat.values() if v[0]]) if stat else None)

if __name__ == "__main__":
    main()
