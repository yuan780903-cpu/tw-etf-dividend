"""巴菲特 + 近代選股邏輯 -> data/value_picks.json(前 50 名 + 原因 + 正常股價區間)
讀 data/fund/fundamentals.json
評分(0~100):
  45% 巴菲特品質   長期高 ROE、獲利穩定成長、毛利護城河、低負債、現金流品質、淨利率
  15% Piotroski F  9 項財務體質是否逐年改善
  15% 神奇公式     資本報酬率高 + 獲利相對市值便宜(Greenblatt)
  10% 動能         近 12 個月扣近 1 月股價動能 + 近 3 個月營收年增(台股常用)
  15% 價格         安全邊際(內在價值 vs 股價)與本益比在自己歷史區間的位置
門檻:上市櫃 5 年以上財報、平均 ROE ≥ 12%、近 5 年都賺錢、市值 ≥ 50 億
正常股價區間:歷年本益比 25% / 50% / 75% 分位 × 近四季 EPS
內在價值:自由現金流(或 EPS)以過去成長率(上限 10%)成長 10 年、折現率 9%、永續成長 2%
"""
import json, os, sys, math, statistics as st, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import shares
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
F = json.load(open(os.path.join(DATA, "fund", "fundamentals.json")))
YEARS = F["years"]; FIX = shares.par_fix(F["companies"])

def r(x, n=1): return None if x is None else round(x, n)
def div(a, b): return a / b if a is not None and b not in (None, 0) else None
def mean(xs): xs = [x for x in xs if x is not None]; return st.mean(xs) if xs else None
def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs: return None
    k = (len(xs) - 1) * q; f = math.floor(k); c = math.ceil(k)
    return xs[f] + (xs[c] - xs[f]) * (k - f)
def cagr(a, b, n):
    return (b / a) ** (1 / n) - 1 if a and b and a > 0 and b > 0 and n > 0 else None

rows = []
for code, c in F["companies"].items():
    Y = c["y"]; ys = [y for y in map(str, YEARS) if y in Y or int(y) in Y]
    get = lambda y: Y.get(y) or Y.get(int(y)) or {}
    ys = [y for y in map(str, YEARS) if get(y)]
    if len(ys) < 5 or not c.get("px") or not c.get("cap") and not get(ys[-1]).get("cap"): continue
    fin = c["fmt"] != "gen"
    ser = {}
    for i, y in enumerate(ys):
        d = get(y); p = get(ys[i - 1]) if i else {}
        eq, eq0 = d.get("eqP") or d.get("eq"), p.get("eqP") or p.get("eq")
        ni = d.get("niP") if d.get("niP") is not None else d.get("ni")
        avg_eq = mean([eq, eq0]) if eq0 else eq
        ser[y] = dict(roe=div(ni, avg_eq) * 100 if div(ni, avg_eq) is not None else None, eps=d.get("eps"), ni=ni,
                      gm=div(d.get("gp"), d.get("rev")) * 100 if div(d.get("gp"), d.get("rev")) is not None else None,
                      nm=div(ni, d.get("rev")) * 100 if div(ni, d.get("rev")) is not None else None,
                      debt=div(d.get("tl"), d.get("ta")) * 100 if div(d.get("tl"), d.get("ta")) is not None else None,
                      cfo=d.get("cfo"), fcf=(d["cfo"] + d["cfi"]) if d.get("cfo") is not None and d.get("cfi") is not None else None,
                      roa=div(ni, d.get("ta")), cr=div(d.get("ca"), d.get("cl")), lev=div(d.get("ncl"), d.get("ta")),
                      at=div(d.get("rev"), d.get("ta")), cap=d.get("cap"), gpa=div(d.get("gp"), d.get("ta")),
                      op=d.get("op"), ta=d.get("ta"), cl=d.get("cl"), ncl=d.get("ncl"), rev=d.get("rev"))
    last = ser[ys[-1]]; ttm = c.get("ttm") or {}
    cap = (ttm.get("cap") or get(ys[-1]).get("cap"))                     # 股本(仟元) -> 股數(千股) = cap/10
    shares_k = FIX[code] / 1000 if code in FIX else cap / 10 if cap else None   # 非 10 元面額用實際股數
    px = c["px"]; mcap = px * shares_k * 1000 / 1e8 if shares_k else None   # 億元
    if not mcap or mcap < 50: continue
    eps_ttm = ttm["niP"] * 1000 / FIX[code] if code in FIX and ttm.get("niP") is not None else ttm.get("eps") if ttm.get("eps") is not None else last["eps"]
    roes = [ser[y]["roe"] for y in ys]; eps = [ser[y]["eps"] for y in ys]
    roe_avg = mean(roes); roe_min5 = min([x for x in roes[-5:] if x is not None], default=None)
    pos_years = sum(1 for x in eps if x is not None and x > 0)
    if roe_avg is None or roe_avg < 12 or any(x is None or x <= 0 for x in eps[-5:]): continue

    # ---------- 巴菲特品質 ----------
    pts, mx, why = 0, 0, []
    mx += 25; pts += 25 if roe_avg >= 20 else 20 if roe_avg >= 15 else 12 if roe_avg >= 12 else 0
    if roe_min5 is not None and roe_min5 < 10: pts -= 8
    why.append(f"{len(ys)} 年平均 ROE {roe_avg:.1f}%（股東每投入 100 元，一年賺約 {roe_avg:.0f} 元）" + ("，近 5 年每年都在 10% 以上" if roe_min5 and roe_min5 >= 10 else ""))
    g_eps = cagr(eps[0], eps_ttm if eps_ttm and eps_ttm > 0 else eps[-1], len(ys) - 1 + (0.75 if c.get("ttm") else 0))
    mx += 20; pts += 10 if pos_years == len(ys) else 5 if pos_years >= len(ys) - 1 else 0
    pts += 10 if (g_eps or 0) >= .10 else 6 if (g_eps or 0) >= .05 else 3 if (g_eps or 0) >= 0 else 0
    why.append(f"{'連續 ' + str(len(ys)) + ' 年都賺錢' if pos_years == len(ys) else str(pos_years) + '/' + str(len(ys)) + ' 年賺錢'}" + (f"，EPS 每年平均成長 {g_eps * 100:.1f}%" if g_eps is not None else ""))
    gms = [ser[y]["gm"] for y in ys]; gm_avg = mean(gms); gm_sd = st.pstdev([x for x in gms if x is not None]) if len([x for x in gms if x is not None]) > 2 else None
    if not fin and gm_avg is not None:
        mx += 15; pts += (10 if gm_avg >= 40 else 7 if gm_avg >= 30 else 3 if gm_avg >= 20 else 0) + (5 if gm_sd is not None and gm_sd <= 3 else 3 if gm_sd is not None and gm_sd <= 6 else 0)
        if gm_avg >= 30: why.append(f"毛利率平均 {gm_avg:.1f}%、上下波動約 {gm_sd:.1f} 個百分點，代表產品有定價能力（護城河）")
    debt = last["debt"]
    if not fin and debt is not None:
        ncl_ok = last["ncl"] is not None and last["ni"] and last["ni"] > 0 and last["ncl"] <= 3 * last["ni"]
        mx += 15; pts += max(15 if debt <= 30 else 10 if debt <= 50 else 5 if debt <= 60 else 0, 10 if ncl_ok else 0)
        why.append(f"負債比 {debt:.0f}%" + ("，財務保守" if debt <= 40 else "，長期負債 3 年內可用獲利還清" if ncl_ok else ""))
    cfo5 = [ser[y]["cfo"] for y in ys[-5:]]; ni5 = [ser[y]["ni"] for y in ys[-5:]]; fcf5 = [ser[y]["fcf"] for y in ys[-5:]]
    cash_q = div(sum(x for x in cfo5 if x is not None), sum(x for x in ni5 if x is not None)) if None not in cfo5 else None
    fcf_pos = sum(1 for x in fcf5 if x is not None and x > 0)
    if not fin and cash_q is not None:
        mx += 15; pts += (10 if cash_q >= 1 else 7 if cash_q >= .8 else 0) + (5 if fcf_pos >= 4 else 3 if fcf_pos >= 3 else 0)
        if cash_q >= .8: why.append(f"近 5 年營業現金流是淨利的 {cash_q:.1f} 倍，賺的是真金白銀")
    nm_avg = mean([ser[y]["nm"] for y in ys])
    if nm_avg is not None:
        mx += 10; pts += 10 if nm_avg >= 20 else 7 if nm_avg >= 10 else 3 if nm_avg >= 5 else 0
    q_buffett = max(0, pts) / mx * 100

    # ---------- Piotroski F ----------
    p0 = ser[ys[-2]]; fpts = []
    def chk(name, ok): fpts.append((name, bool(ok)))
    chk("ROA>0", (last["roa"] or 0) > 0); chk("營業現金流>0", (last["cfo"] or 0) > 0)
    chk("ROA 提升", last["roa"] is not None and p0["roa"] is not None and last["roa"] > p0["roa"])
    chk("現金流>淨利", last["cfo"] is not None and last["ni"] is not None and last["cfo"] > last["ni"])
    chk("長期負債比下降", last["lev"] is not None and p0["lev"] is not None and last["lev"] <= p0["lev"])
    chk("流動比率提升", last["cr"] is not None and p0["cr"] is not None and last["cr"] > p0["cr"])
    chk("沒有大幅增資", last["cap"] and p0["cap"] and last["cap"] <= p0["cap"] * 1.02)
    chk("毛利率提升", last["gm"] is not None and p0["gm"] is not None and last["gm"] > p0["gm"])
    chk("資產周轉率提升", last["at"] is not None and p0["at"] is not None and last["at"] > p0["at"])
    fscore = sum(ok for _, ok in fpts)

    # ---------- 神奇公式 / 品質 / 動能 ----------
    roc = div(last["op"], (last["ta"] or 0) - (last["cl"] or 0)) if not fin else None
    ey = div(last["op"], mcap * 1e5 + (last["ncl"] or 0)) if not fin and last["op"] else None   # mcap 億 -> 仟元 *1e5
    mom = div(c.get("px1m"), c.get("px12m")) - 1 if div(c.get("px1m"), c.get("px12m")) else None
    revs = c.get("rev") or []
    ryoy = mean([(x[1] / x[2] - 1) * 100 for x in revs[:3] if x[1] and x[2]])

    # ---------- 估價 ----------
    pes = []
    for y in ys:
        pxy = (c.get("pxY") or {}).get(y) or (c.get("pxY") or {}).get(int(y)) if c.get("pxY") else None
        e = ser[y]["eps"]
        if pxy and e and e > 0 and pxy / e < 80: pes.append(pxy / e)
    base_eps = eps_ttm if eps_ttm and eps_ttm > 0 else last["eps"]
    pe_lo, pe_mid, pe_hi = (pct(pes, .25), pct(pes, .5), pct(pes, .75)) if len(pes) >= 4 else (10, 14, 18)
    band = dict(cheap=r(base_eps * pe_lo, 1), fair=r(base_eps * pe_mid, 1), rich=r(base_eps * pe_hi, 1),
                peLo=r(pe_lo), peMid=r(pe_mid), peHi=r(pe_hi), nPE=len(pes))
    pe_now = px / base_eps if base_eps else None
    fcf3 = [ser[y]["fcf"] for y in ys[-3:] if ser[y]["fcf"] is not None]
    fcf_ps = st.median(fcf3) / shares_k if fcf3 and shares_k else None
    owner = base_eps * 0.8 if fin else max(fcf_ps or 0, base_eps * 0.7)   # 擴產期資本支出大會壓低自由現金流 -> 至少用 EPS 七成
    g = max(0.0, min(0.10, g_eps or 0)); dr, tg = 0.09, 0.02
    iv, cf = 0.0, owner
    for t in range(1, 11):
        cf *= 1 + g; iv += cf / (1 + dr) ** t
    iv += cf * (1 + tg) / (dr - tg) / (1 + dr) ** 10
    mos = (iv - px) / iv if iv > 0 else None
    pos_band = (px - band["cheap"]) / (band["rich"] - band["cheap"]) if band["rich"] and band["cheap"] and band["rich"] > band["cheap"] else None
    vscore = max(0, min(100, 50 + (mos or 0) * 100)) * .6 + max(0, min(100, 100 - (pos_band if pos_band is not None else .5) * 100)) * .4

    rows.append(dict(id=code, name=c["name"], ind=c.get("ind"), mkt=c.get("mkt"), fin=fin, px=px, mcap=r(mcap, 0),
                     qB=r(q_buffett), f=fscore, fItems=fpts, roc=roc, ey=ey, mom=mom, ryoy=ryoy, vscore=vscore,
                     roeAvg=r(roe_avg), roeMin5=r(roe_min5), gEps=r(g_eps * 100 if g_eps is not None else None), gmAvg=r(gm_avg), gmSd=r(gm_sd),
                     nmAvg=r(nm_avg), debt=r(debt), cashQ=r(cash_q, 2), fcfPos=fcf_pos, epsTTM=r(base_eps, 2), peNow=r(pe_now),
                     band=band, iv=r(iv, 1), mos=r(mos * 100 if mos is not None else None), owner=r(owner, 2), g=r(g * 100),
                     series=dict(years=ys, roe=[r(x) for x in roes], eps=[r(x, 2) for x in eps], gm=[r(x) for x in gms]),
                     why=why, ttmLabel=c.get("ttmLabel")))

# ---------- 排名百分位(神奇公式、動能) ----------
def prank(key, rev=False):
    vals = sorted(x[key] for x in rows if x[key] is not None)
    for x in rows:
        v = x[key]
        x[key + "P"] = None if v is None else (sum(1 for y in vals if y <= v) / len(vals) * 100)
for k in ("roc", "ey", "mom", "ryoy"): prank(k)
for x in rows:
    magic = mean([x["rocP"], x["eyP"]]) if not x["fin"] else None
    momo = mean([x["momP"], x["ryoyP"]])
    x["magicP"] = r(magic); x["momoP"] = r(momo)
    parts = [(x["qB"], .45), (x["f"] / 9 * 100, .15), (magic, .15), (momo, .10), (x["vscore"], .15)]
    w = sum(wt for v, wt in parts if v is not None)
    x["score"] = r(sum(v * wt for v, wt in parts if v is not None) / w)
    # 補充原因
    if x["f"] >= 7: x["why"].append(f"F 分數 {x['f']}/9：財務體質正在變好（{'、'.join(n for n, ok in x['fItems'] if ok)}）")
    elif x["f"] <= 3: x["why"].append(f"F 分數僅 {x['f']}/9：最近一年財務體質轉弱，要留意")
    if magic is not None and magic >= 70: x["why"].append(f"神奇公式排名前 {100 - magic:.0f}%：資本報酬率高、相對市值又不貴")
    if x["ryoy"] is not None: x["why"].append(f"近 3 個月營收平均年增 {x['ryoy']:+.1f}%" + ("，成長動能佳" if x["ryoy"] >= 10 else "，營收轉弱" if x["ryoy"] < -5 else ""))
    b = x["band"]
    if x["peNow"]:
        rel = "低於" if x["peNow"] < b["peMid"] else "高於"
        x["why"].append(f"目前本益比 {x['peNow']:.1f} 倍，{rel}自己歷年中位數 {b['peMid']:.1f} 倍")
    if x["mos"] is not None:
        x["why"].append(f"估算內在價值約 {x['iv']:,.0f} 元，" + (f"股價有 {x['mos']:.0f}% 安全邊際" if x["mos"] > 0 else f"股價已高於內在價值 {-x['mos']:.0f}%"))
    x["zone"] = "便宜" if x["px"] <= b["cheap"] else "合理偏低" if x["px"] <= b["fair"] else "合理偏高" if x["px"] <= b["rich"] else "偏貴"
    x["vS"] = r(x["vscore"])
    for k in ("roc", "ey", "mom", "vscore", "rocP", "eyP", "momP", "ryoyP"): x.pop(k, None)
    x["ryoy"] = r(x["ryoy"])

rows.sort(key=lambda x: -x["score"])
for i, x in enumerate(rows, 1): x["rank"] = i
out = dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), source=F["updated"], years=YEARS, latest=F.get("latest"),
           universe=len(rows), top=rows[:50], others=rows[50:150],   # 第 51~150 名也輸出完整資料(網頁同樣顯示詳細卡片)
           method=dict(weights={"巴菲特品質": 45, "Piotroski F 分數": 15, "神奇公式": 15, "動能（股價＋營收）": 10, "價格（安全邊際＋本益比位置）": 15},
                       gate="5 年以上財報、平均 ROE ≥ 12%、近 5 年每年都賺錢、市值 ≥ 50 億", dcf="自由現金流與 EPS×0.7 取高者（金融業用 EPS×0.8）以過去 EPS 成長率（上限 10%）成長 10 年，折現率 9%，永續成長 2%"))
json.dump(out, open(os.path.join(DATA, "value_picks.json"), "w"), ensure_ascii=False, separators=(",", ":"))
print(f"value_picks.json:通過門檻 {len(rows)} 家,前 50 名:")
for x in rows[:50]:
    print(f"{x['rank']:>2} {x['id']} {x['name'][:6]:6s} {x['ind'] or '':8s} 分{x['score']:5.1f} 品{x['qB']:5.1f} F{x['f']} 神{x['magicP'] or 0:5.1f} 動{x['momoP'] or 0:5.1f} ROE{x['roeAvg']:5.1f} 價{x['px']:>8} 區間{x['band']['cheap']}/{x['band']['fair']}/{x['band']['rich']} {x['zone']} MOS{x['mos']}")
