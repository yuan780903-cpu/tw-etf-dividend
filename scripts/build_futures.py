"""外資台指期空單(三大法人台指期淨未平倉)分析 -> data/futures.json
資料:market.json 的 ffi/fit/fdl(FinMind 期交所三大法人「臺股期貨」未平倉,與看盤軟體「法人→未平倉」相同)
算:
  1. 今天各法人淨未平倉、1/5/20/120 日增減(增減≈當天交易口數)
  2. 合理區間:近一年百分位(外資單看會因投信槓桿 ETF 越來越大而失真,另算「外資＋投信」=扣掉 ETF 對作後的真實淨空)
  3. 空單成本:近 20 日新增空單均價、近 120 日持倉估算成本 → 指數漲過這個價位,外資空單開始賠錢(可能回補＝軋空)
  4. 空單價值與避險比例:空單口數 × 指數 × 200 元 ÷ 外資持有上市股票市值
  5. 歷史對照:同樣狀態之後 5/20 日大盤平均漲跌與上漲機率
用法: python3 scripts/build_futures.py
"""
import json, os, sys, time, datetime as dt, urllib.request, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh, net  # noqa: F401  (net:證交所 cookie)
DATA = fh.DATA; UA = {"User-Agent": "Mozilla/5.0"}
MULT = 200                                            # 大台指期每點 200 元

def get(u):
    for k in range(3):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read())
        except Exception as e:
            if k == 2: print("  失敗", u[:70], e)
            time.sleep(2 + 3 * k)

def q(v, p):
    v = sorted(x for x in v if x is not None)
    return v[int(p * (len(v) - 1))] if v else None
def prank(v, x):
    v = [y for y in v if y is not None]
    return round(sum(1 for y in v if y <= x) / len(v) * 100) if v and x is not None else None

def foreign_hold(days):
    """外資持有上市股票市值(億元):證交所 MI_QFIIS 全體外資持股股數 × 收盤價"""
    px = {}
    import quotes                                  # 官網當日行情優先
    for x in quotes.twse_all():
        try: px[x["Code"]] = float(x["ClosingPrice"])
        except Exception: pass
    for d in reversed(days[-5:]):
        j = get(f"https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date={d.replace('-', '')}&response=json&selectType=ALLBUT0999")
        if j and j.get("stat") == "OK" and j.get("data"):
            v = 0
            for r in j["data"]:
                try: v += float(r[5].replace(",", "")) * px.get(r[0], 0)
                except Exception: pass
            if v > 0: return round(v / 1e8), d
        time.sleep(1.2)
    return None, None

def main():
    M = json.load(open(os.path.join(DATA, "market.json"))); C = M["cols"]
    R = [dict(zip(C, r)) for r in M["rows"] if r[C.index("ffi")] is not None and r[C.index("tx")]]
    n = len(R); D = [r["d"] for r in R]; P = [r["tx"] for r in R]
    fi = [r["ffi"] for r in R]; it = [r["fit"] or 0 for r in R]; dl = [r["fdl"] or 0 for r in R]
    fiit = [a + b for a, b in zip(fi, it)]; tot = [a + b + c for a, b, c in zip(fi, it, dl)]
    L = n - 1
    chg = lambda s, k: s[L] - s[L - k] if L - k >= 0 else None
    now = dict(fi=fi[L], it=it[L], dl=dl[L], tot=tot[L], fiit=fiit[L])
    ch = {k: [chg(s, 1), chg(s, 5), chg(s, 20), chg(s, 120)] for k, s in (("fi", fi), ("it", it), ("dl", dl), ("tot", tot), ("fiit", fiit))}
    # 合理區間(近一年＝250 個交易日;另附 5 年)
    def zone(s, w=250):
        x = s[-w:]
        return dict(p10=q(x, .1), p25=q(x, .25), p50=q(x, .5), p75=q(x, .75), p90=q(x, .9), min=min(x), max=max(x), pct=prank(x, s[L]))
    zones = dict(fi=zone(fi), fiit=zone(fiit), tot=zone(tot), fi5y=zone(fi, 9999))
    # 空單成本(以加權指數收盤近似台指期價格)
    add = [(P[i], (fi[i - 1] - fi[i])) for i in range(max(1, L - 19), L + 1) if fi[i] < fi[i - 1]]   # 外資空單增加的日子:新增口數 × 當天指數
    add20 = round(sum(p * q_ for p, q_ in add) / sum(q_ for _, q_ in add)) if add else None
    add20n = sum(q_ for _, q_ in add)
    s0 = max(0, L - 120); pos = max(0, -fi[s0]); cost = P[s0]            # 120 日前的空單先用當天指數當成本,之後逐日加權
    for i in range(s0 + 1, L + 1):
        short, prev = max(0, -fi[i]), max(0, -fi[i - 1])
        if short > prev: cost = (cost * prev + P[i] * (short - prev)) / short if short else cost
        pos = short
    cost120 = round(cost) if pos else None
    pnl = round((cost120 - P[L]) * pos * MULT / 1e8, 1) if cost120 else None          # 正＝空單帳上賺錢(億元)
    notional = round(-fi[L] * P[L] * MULT / 1e8) if fi[L] < 0 else 0                     # 外資空單契約價值(億元)
    fiit_notional = round(-fiit[L] * P[L] * MULT / 1e8) if fiit[L] < 0 else 0
    hold, hold_d = foreign_hold(D)
    ratio = round(notional / hold * 100, 2) if hold else None
    ratio2 = round(fiit_notional / hold * 100, 2) if hold else None
    # 歷史對照:之後 5/20 日加權指數漲跌(同一狀態 10 天內重複只算一次)
    def fwd(i, h): return (P[i + h] / P[i] - 1) * 100 if i + h < n else None
    roll = [prank(fiit[max(0, i - 249):i + 1], fiit[i]) if i >= 120 else None for i in range(n)]       # 「外資＋投信」在當時近一年的百分位
    def stat(cond, name, desc):
        idx, lastk = [], -99
        for i in range(n):
            if cond(i):
                if i - lastk > 10: idx.append(i)
                lastk = i
        o = dict(name=name, desc=desc, n=len(idx), last=D[idx[-1]] if idx else None)
        for h in (5, 20):
            xs = [fwd(i, h) for i in idx if fwd(i, h) is not None]
            o[f"r{h}"] = round(st.mean(xs), 2) if xs else None; o[f"w{h}"] = round(sum(x > 0 for x in xs) / len(xs) * 100) if xs else None; o[f"n{h}"] = len(xs)
        o["now"] = bool(cond(L)); return o
    base = [i for i in range(n) if roll[i] is not None]
    def all_days():
        o = dict(name="所有交易日（對照組）", desc="不分狀態的平常表現", n=len(base), now=False, last=None)
        for h in (5, 20):
            xs = [fwd(i, h) for i in base if fwd(i, h) is not None]
            o[f"r{h}"] = round(st.mean(xs), 2); o[f"w{h}"] = round(sum(x > 0 for x in xs) / len(xs) * 100); o[f"n{h}"] = len(xs)
        return o
    bt = [all_days(),
          stat(lambda i: roll[i] is not None and roll[i] <= 10, "真實淨空偏多（近一年最空的 10%）", "外資＋投信的淨空單，落在近一年最空的 10% 區間"),
          stat(lambda i: roll[i] is not None and roll[i] >= 90, "真實淨空偏少（近一年最不空的 10%）", "外資＋投信幾乎不空、甚至偏多"),
          stat(lambda i: i >= 5 and fi[i] - fi[i - 5] <= -10000, "外資 5 日加空 1 萬口以上", "一週內外資空單大增"),
          stat(lambda i: i >= 5 and fi[i] - fi[i - 5] >= 10000, "外資 5 日回補 1 萬口以上", "一週內外資大量回補空單")]
    # 白話判讀
    z, zz = zones["fi"], zones["fiit"]
    lvl = lambda pct: "非常偏空" if pct <= 10 else "偏空" if pct <= 25 else "正常" if pct < 75 else "偏多" if pct < 90 else "非常偏多"
    say = [f"外資台指期淨空 {-fi[L]:,} 口（契約價值約 {notional:,} 億元），在近一年第 {z['pct']} 百分位（{lvl(z['pct'])}）；今天{'加空' if ch['fi'][0] < 0 else '回補'} {abs(ch['fi'][0]):,} 口，近 5 日{'加空' if ch['fi'][1] < 0 else '回補'} {abs(ch['fi'][1]):,} 口。",
           f"但投信同時有 {it[L]:,} 口多單（多半是槓桿 ETF「正 2」為了做到兩倍漲跌而買的期貨），外資常是另一邊的避險／套利者。扣掉這部分，外資＋投信的「真實淨空」只有 {-fiit[L]:,} 口，在近一年第 {zz['pct']} 百分位（{lvl(zz['pct'])}）。"]
    if ratio is not None:
        say.append(f"外資手上持有上市股票約 {hold / 1e4:,.1f} 兆元，期貨空單價值只占 {ratio}%（扣掉 ETF 對作只占 {ratio2}%），比較像替現股買保險（避險），不等於全面看壞台股。")
    if cost120:
        say.append(f"估算外資空單成本：近 120 日持倉約 {cost120:,} 點" + (f"、近 20 日新增的空單平均約 {add20:,} 點" if add20 else "") + f"。指數 {P[L]:,.0f} 點{'低於' if P[L] < cost120 else '高於'}成本，空單帳上{'賺' if pnl > 0 else '賠'}約 {abs(pnl):,.0f} 億；指數漲過 {cost120:,} 點，空單開始賠錢，回補（軋空）的壓力會變大。")
    out = dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), d=D[L], px=P[L], now=now, chg=ch, zones=zones,
               cost=dict(add20=add20, add20n=add20n, pos120=cost120, pos=pos, pnl=pnl), notional=notional, fiitNotional=fiit_notional,
               hold=hold, holdD=hold_d, ratio=ratio, ratio2=ratio2, bt=bt, say=say,
               H=[[D[i], P[i], fi[i], it[i], dl[i]] for i in range(max(0, n - 250), n)],
               note="大台指期(TX)三大法人淨未平倉(多單−空單,口);每口契約價值＝指數×200 元;成本以加權指數收盤近似;歷史對照為過去統計,不代表未來")
    fh.save(os.path.join(DATA, "futures.json"), out)
    print(f"futures.json:{D[L]} 外資 {fi[L]:,}({z['pct']}%) 投信 {it[L]:,} 外資+投信 {fiit[L]:,}({zz['pct']}%) 成本120 {cost120} 新增20 {add20} 損益 {pnl} 億 避險 {ratio}%")
    for s in say: print("  ", s)

if __name__ == "__main__":
    main()
