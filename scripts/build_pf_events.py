"""配息提醒用的事件表 -> data/pf_events.json(雲端推播 Worker etf-alert 每天早上讀這一個檔,幫訂閱的人比對「我的配息試算」持股)
讀 data/summary.json、data/upcoming.json(證交所除權息預告)、data/dividends/<id>.json、data/prices/<id>.json、data/calendar.json(台股休市日)

每檔 ETF 只放「有事」的:
  ex   即將除息(今天～45 天內,已公告):[除息日, 每股現金(未公布為 null), 最後買進日(除息日前一個交易日)]
  pay  即將入帳(今天～45 天內,已公告發放日):[發放日, 每股現金, 除息日]
  fill 最近一次除息(75 天內)的填息狀況:[除息日, 每股現金, 除息前一天收盤, 第幾個交易日填息(未填 null), 除息後已過交易日數, 填息那天(未填 null), 最新收盤]
填息＝除息後收盤價漲回除息前一天收盤(和網站「我的配息提醒」、個股填息紀錄同一個定義)。
"""
import json, os, datetime as dt

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
AHEAD = 45
FILL_DAYS = 75


def load(p, default=None):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return default


def today_tpe():
    return (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()


def tw_holidays():
    c = load(os.path.join(DATA, "calendar.json"), {}) or {}
    return {e.get("d") for e in (c.get("ev") or []) if e.get("key") == "TWHOL" and e.get("d")}


def prev_trading(day, hol):
    d = dt.date.fromisoformat(day) - dt.timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in hol: d -= dt.timedelta(days=1)
    return d.isoformat()


def fill_of(px, ex, cash):
    pre = [r for r in px if r[0] < ex]
    aft = [r for r in px if r[0] >= ex]
    if not pre or not aft: return None
    p0 = pre[-1][4]
    k = next((i for i, r in enumerate(aft) if r[4] >= p0), None)
    return [ex, cash, p0, None if k is None else k + 1, len(aft), None if k is None else aft[k][0], aft[-1][4]]


def main():
    S = load(os.path.join(DATA, "summary.json"), {}) or {}
    etfs = S.get("etfs") or []
    U = load(os.path.join(DATA, "upcoming.json"), []) or []
    hol = tw_holidays()
    td = today_tpe(); tds = td.isoformat(); end = (td + dt.timedelta(days=AHEAD)).isoformat(); back = (td - dt.timedelta(days=FILL_DAYS)).isoformat()
    out = {}
    for e in etfs:
        sid = e.get("id")
        if not sid: continue
        H = load(os.path.join(DATA, "dividends", sid + (".adj" if e.get("adj") else "") + ".json"), []) or []
        ev = {}
        exs = {}
        for u in U:
            if u.get("id") == sid and tds <= (u.get("ex") or "") <= end: exs[u["ex"]] = u.get("cash")
        for d in H:
            x = d.get("ex") or ""
            if tds <= x <= end and exs.get(x) is None: exs[x] = d.get("cash")
        if exs: ev["ex"] = [[x, exs[x], prev_trading(x, hol)] for x in sorted(exs)]
        pay = [[d["pay"], d.get("cash"), d.get("ex")] for d in H if d.get("pay") and tds <= d["pay"] <= end and d.get("cash")]
        if pay: ev["pay"] = sorted(pay)
        last = [d for d in H if d.get("ex") and back <= d["ex"] <= tds and d.get("cash")]
        if last:
            f = fill_of(load(os.path.join(DATA, "prices", sid + ".json"), []) or [], last[-1]["ex"], last[-1]["cash"])
            if f: ev["fill"] = f
        if ev:
            ev["n"] = e.get("name") or sid
            out[sid] = ev
    res = dict(updated=(dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"), day=tds, e=out)
    with open(os.path.join(DATA, "pf_events.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    print(f"pf_events.json: {len(out)} 檔有事件(除息 {sum('ex' in v for v in out.values())}、入帳 {sum('pay' in v for v in out.values())}、填息追蹤 {sum('fill' in v for v in out.values())})")


if __name__ == "__main__":
    main()
