"""風險雷達 -> data/risk.json
- 處置股、注意股(證交所 OpenAPI + 櫃買 OpenAPI)
- 借券賣出餘額(上市 TWT93U 可回補歷史;上櫃 tpex_margin_sbl 只有當日,逐日累積)
- 外資持股比率(上市 MI_QFIIS 可回補;上櫃 tpex_3insti_qfii 逐日累積)
- 當沖比(上市 TWTB4U 個股當沖股數 ÷ 成交量)
歷史快取:data/risk/raw/YYYYMMDD.json(保留 30 個交易日)
風險旗標:處置中、注意股、借券 5 日增加 30% 以上且餘額≥1000 張、外資持股 20 日減少 2 個百分點以上、當沖比≥50%
"""
import json, os, sys, time, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh, net  # noqa: F401  (net 安裝帶 cookie 的 opener,證交所會 307)
import urllib.request
DATA = fh.DATA; RAW = os.path.join(DATA, "risk", "raw"); os.makedirs(RAW, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}
N = lambda x: (lambda s: float(s) if s.replace(".", "", 1).replace("-", "", 1).isdigit() else None)(str(x).replace(",", "").replace("%", "").strip())
STOCK = lambda c: isinstance(c, str) and len(c) == 4 and c.isdigit() and not c.startswith("00")   # 個股(排除 ETF)

def get(u, t=90):
    for k in range(3):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t).read())
        except Exception as e:
            if k == 2: print("  失敗", u[:80], e)
            time.sleep(2 + k * 3)
    return None

import re
def roc(t):
    """民國日期區間(1151120~1151126 或 115/11/23～115/11/27)→ 11/20～11/26"""
    m = re.findall(r"1\d{2}/?(\d{2})/?(\d{2})", t or "")
    return "～".join(f"{int(a)}/{int(b)}" for a, b in m) or (t or "")

def twse_day(d):
    """上市:借券賣出餘額(股)、外資持股比、當沖股數"""
    out = {"sbl": {}, "qf": {}, "dt": {}}
    j = get(f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date={d}&response=json")
    if j and j.get("stat") == "OK":
        for r in j["data"]:
            if STOCK(r[0]) and N(r[12]) is not None: out["sbl"][r[0]] = N(r[12])
    time.sleep(1.2)
    j = get(f"https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date={d}&response=json&selectType=ALLBUT0999")
    if j and j.get("stat") == "OK":
        for r in j["data"]:
            if STOCK(r[0]) and N(r[7]) is not None: out["qf"][r[0]] = N(r[7])
    time.sleep(1.2)
    j = get(f"https://www.twse.com.tw/exchangeReport/TWTB4U?response=json&date={d}&selectType=All")
    if j and j.get("stat") == "OK":
        for t in j.get("tables", []):
            if t.get("fields") and t["fields"][0] == "證券代號":
                for r in t.get("data", []):
                    if STOCK(r[0]) and N(r[3]) is not None: out["dt"][r[0]] = N(r[3])
    time.sleep(1.2)
    return out

def main():
    M = json.load(open(os.path.join(DATA, "market.json")))
    days = [r[0].replace("-", "") for r in M["rows"][-30:]]
    have = {f[:8] for f in os.listdir(RAW) if f.endswith(".json")}
    # 回補上市歷史(第一次會補約 25 天,之後每天只抓新的)
    for d in days[-25:]:
        if d in have: continue
        o = twse_day(d)
        if o["sbl"] or o["qf"]:
            fh.save(os.path.join(RAW, d + ".json"), o); have.add(d); print("  風險資料", d, len(o["sbl"]), len(o["qf"]), len(o["dt"]))
    last = days[-1]
    # 上櫃只有當日:併入最新一天
    cur = json.load(open(os.path.join(RAW, last + ".json"))) if last in have else {"sbl": {}, "qf": {}, "dt": {}}
    sb = get("https://www.tpex.org.tw/openapi/v1/tpex_margin_sbl") or []
    if sb and sb[0].get("Date") and str(int(sb[0]["Date"][:3]) + 1911) + sb[0]["Date"][3:] == last:
        for r in sb:
            c = r.get("SecuritiesCompanyCode")
            if STOCK(c) and N(r.get("SecuritiesBorrowingBalanceOfTheMarketDay")) is not None: cur["sbl"][c] = N(r["SecuritiesBorrowingBalanceOfTheMarketDay"])
    qo = get("https://www.tpex.org.tw/openapi/v1/tpex_3insti_qfii") or []
    if qo and qo[0].get("Date") and str(int(qo[0]["Date"][:3]) + 1911) + qo[0]["Date"][3:] == last:
        for r in qo:
            c = r.get("SecuritiesCompanyCode")
            if STOCK(c) and N(r.get("PercentageOfSharesOC/FMIHeld")) is not None: cur["qf"][c] = N(r["PercentageOfSharesOC/FMIHeld"])
    if cur["sbl"] or cur["qf"]: fh.save(os.path.join(RAW, last + ".json"), cur)
    files = sorted(f for f in os.listdir(RAW) if f.endswith(".json"))
    for f in files[:-30]: os.remove(os.path.join(RAW, f))
    files = files[-30:]
    H = [json.load(open(os.path.join(RAW, f))) for f in files]
    # 處置/注意
    disp, att = {}, {}
    for r in get("https://openapi.twse.com.tw/v1/announcement/punish") or []:
        if STOCK(r.get("Code")): disp[r["Code"]] = dict(n=r.get("Name"), why=r.get("ReasonsOfDisposition"), per=roc(r.get("DispositionPeriod")), how=(r.get("DispositionMeasures") or "")[:60], m="上市")
    for r in get("https://www.tpex.org.tw/openapi/v1/tpex_disposal_information") or []:
        c = r.get("SecuritiesCompanyCode")
        if STOCK(c): disp[c] = dict(n=r.get("CompanyName"), why=(r.get("DispositionReasons") or "")[:40], per=roc(r.get("DispositionPeriod")), how="", m="上櫃")
    for r in get("https://openapi.twse.com.tw/v1/announcement/notice") or []:
        if STOCK(r.get("Code")): att[r["Code"]] = dict(n=r.get("Name"), why=(r.get("TradingInfoForAttention") or "")[:60], m="上市")
    for r in get("https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_information") or []:
        c = r.get("SecuritiesCompanyCode")
        if STOCK(c): att[c] = dict(n=r.get("CompanyName"), why=(r.get("TradingInformation") or "")[:60], m="上櫃")
    # 個股指標
    hm = {x[0]: x for x in (json.load(open(os.path.join(DATA, "heatmap.json"))).get("items", []) if os.path.exists(os.path.join(DATA, "heatmap.json")) else [])}
    def ago(k, c, n):
        vs = [h[k].get(c) for h in H]
        return vs[-1], (vs[-1 - n] if len(vs) > n else None)
    codes = set(H[-1]["sbl"]) | set(H[-1]["qf"]) | set(disp) | set(att)
    S, flags = {}, {}
    for c in codes:
        s0, s5 = ago("sbl", c, 5); _, s20 = ago("sbl", c, 20); q0, q5 = ago("qf", c, 5); _, q20 = ago("qf", c, 20)
        dtv = H[-1]["dt"].get(c); vol = hm.get(c, [None] * 7)[6]
        dtr = round(dtv / 1000 / vol * 100, 1) if dtv and vol else None
        r = lambda a, b: round((a / b - 1) * 100, 1) if a is not None and b else None
        d = lambda a, b: round(a - b, 2) if a is not None and b is not None else None
        S[c] = [round(s0 / 1000) if s0 is not None else None, r(s0, s5), r(s0, s20), q0, d(q0, q5), d(q0, q20), dtr]
        f = []
        if c in disp: f.append("處置股")
        if c in att: f.append("注意股")
        if S[c][1] is not None and S[c][1] >= 30 and (S[c][0] or 0) >= 1000: f.append(f"借券賣出 5 日增 {S[c][1]}%")
        if S[c][5] is not None and S[c][5] <= -2: f.append(f"外資持股 20 日減 {abs(S[c][5])} 個百分點")
        if dtr is not None and dtr >= 50: f.append(f"當沖比 {dtr}%")
        if f: flags[c] = f
    fh.save(os.path.join(DATA, "risk.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), d=last, days=len(H),
            cols=["借券賣出餘額(張)", "借券5日%", "借券20日%", "外資持股%", "外資持股5日變化", "外資持股20日變化", "當沖比%"], s=S, disp=disp, att=att, flags=flags,
            note="處置/注意股來自證交所與櫃買公告;借券賣出餘額、外資持股比率每日收盤後更新(上櫃歷史自 2026-11-23 起逐日累積);當沖比僅上市"))
    print(f"risk.json:{len(S)} 檔,處置 {len(disp)}、注意 {len(att)}、風險旗標 {len(flags)};歷史 {len(H)} 天")

if __name__ == "__main__":
    main()
