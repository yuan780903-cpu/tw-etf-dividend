"""專家選股:用 MoneyDJ「大師選股」公布的 9 位大師條件,篩選全部上市櫃公司 -> data/experts.json
資料:data/fund/fundamentals.json(fetch_fundamentals.py)+ 董監持股(證交所/櫃買 OpenAPI)
共同過濾:股價 5 元以下、五日均量 500 張以下不列入
"""
import json, os, sys, statistics as st, datetime as dt, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh, shares
DATA = fh.DATA; F = json.load(open(os.path.join(DATA, "fund", "fundamentals.json")))
YEARS = F["years"]; Y = [str(y) for y in YEARS]
UA = {"User-Agent": "Mozilla/5.0"}

def director_pct():
    """董監持股合計(股)→ 之後除以總股數"""
    out = {}; cp = os.path.join(DATA, "fund", "raw", "directors.json")
    cache = json.load(open(cp)) if os.path.exists(cp) else {}
    for key, url in (("twse", "https://openapi.twse.com.tw/v1/opendata/t187ap11_L"), ("tpex", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O")):
        try:
            rows = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read())
        except Exception as e:
            print("董監持股失敗,沿用上次資料", url, e); out.update(cache.get(key, {})); continue
        part = {}
        for r in rows:
            c = r.get("公司代號") or r.get("SecuritiesCompanyCode"); t = r.get("職稱") or r.get("Title") or ""
            if not c or not any(k in t for k in ("董事", "監察人")): continue
            try: v = float(str(r.get("目前持股") or r.get("CurrentShareholding") or 0).replace(",", ""))
            except ValueError: continue
            part[c] = part.get(c, 0) + v
        if part: cache[key] = part; out.update(part)
    if cache: fh.save(cp, cache)
    print("董監持股", len(out), "家"); return out

def g(a, b):                       # 成長率 %
    if a is None or b is None or b == 0: return None
    return (a - b) / abs(b) * 100
def ser(d, k): return [(d["y"].get(y) or {}).get(k) for y in Y]
def rates(v, n):                   # 最近 n 年的年成長率
    r = [g(v[i], v[i - 1]) for i in range(len(v) - n, len(v))]
    return None if any(x is None for x in r) else r
def avg(r): return None if not r else sum(r) / len(r)
def ratio(a, b): return None if a is None or not b else a / b * 100
R = lambda x, n=2: None if x is None else round(x, n)

EXPERTS = [
  dict(id="lynch", name="彼得林區", en="Peter Lynch", tag="成長股獵人",
       say="富達麥哲倫基金傳奇經理人，13 年平均年報酬 29%。他相信「買你看得懂、正在快速成長、價格又不貴的公司」，最愛本益比低於成長率的股票，也很在意公司不要借太多錢。",
       rules=["本益比小於 20", "近 2 年營收成長率平均大於 25%", "近 5 年稅前淨利成長率平均大於 7%", "最近一季負債比小於 30%"]),
  dict(id="graham", name="班哲明格拉罕", en="Benjamin Graham", tag="價值投資之父",
       say="巴菲特的老師，《智慧型股票投資人》作者。核心是「安全邊際」：只買穩定賺錢、財務非常健康、而且價格遠低於資產價值的便宜股，寧可錯過也不要買貴。",
       rules=["近 5 年每年 EPS 都大於 0 元", "本益比小於 15", "近 12 個月營收大於 3 億元", "股價淨值比小於 1.5", "最新財報流動比率大於 200%", "近 5 年稅前淨利成長率平均大於 3%"]),
  dict(id="buffett", name="華倫巴菲特", en="Warren Buffett", tag="股神",
       say="波克夏公司董事長，史上最成功的投資人之一。「用合理的價格買進好公司，然後長期持有」：要每年穩定賺錢、毛利率夠高（有護城河）、股東權益報酬率好，價格不能太貴。",
       rules=["近 5 年每年 EPS 都大於 1 元", "近 12 個月每股營收大於 1.5 元", "股價淨值比小於 1.5", "近 4 季股東權益報酬率大於 5%", "近 5 年毛利率每年都大於 10%"]),
  dict(id="osh", name="詹姆士歐沙那希", en="James O'Shaughnessy", tag="量化選股先驅",
       say="《What Works on Wall Street》作者，用 40 多年的歷史數據回測找出真正有效的選股因子。他的組合是「高成長＋低本益比＋高且持續變好的獲利能力」。",
       rules=["近 5 年 EPS 成長率平均大於 15%", "本益比小於 18", "近 4 季股東權益報酬率大於 18%", "近 4 季股東權益報酬率比上一年度提升 15% 以上"]),
  dict(id="murphy", name="麥克墨菲", en="Michael Murphy", tag="科技成長股專家",
       say="科技股投資專家，《科技股投資聖經》作者。他認為科技公司要看營收能不能持續高速成長，同時本業要真的賺錢，不能只燒錢衝營收。",
       rules=["近 3 年營收成長率平均大於 15%", "近 4 季股東權益報酬率大於 7%", "最新財報營業利益率大於 1%", "近 3 年營業利益率每年都大於 3%"]),
  dict(id="kfisher", name="肯尼斯費雪", en="Kenneth Fisher", tag="營收成長派",
       say="費雪投資創辦人、成長股大師菲利普費雪之子，提出「股價營收比」選股法。他重視營收長期成長、獲利跟著成長，而且公司負債要低，經得起景氣循環。",
       rules=["近 5 年營收成長率平均大於 15%", "近 5 年稅前淨利成長率平均大於 5%", "最近一季負債比小於 30%"]),
  dict(id="yusko", name="馬克約克奇", en="Mark Yusko", tag="穩定成長派",
       say="摩根溪資本創辦人，曾管理北卡大學校務基金。他偏好獲利「每一年都穩定成長」的公司，不要大起大落，長期複利效果最好。",
       rules=["近 5 年稅前淨利成長率每年都大於 5%", "近 5 年稅前淨利成長率平均大於 10%", "最新財報毛利率大於 4%"]),
  dict(id="sivy", name="麥克喜偉", en="Michael Sivy", tag="合理價成長派",
       say="《Money》雜誌資深投資專欄作家。他找的是「營收每年都穩定成長、獲利能力好、幾乎不借錢，而且本益比還算合理」的優質成長股。",
       rules=["本益比小於 20", "近 5 年營收成長率每年都大於 10%", "近 4 季股東權益報酬率大於 15%", "最近一季負債比小於 20%"]),
  dict(id="price", name="麥克普萊斯", en="Michael Price", tag="深度價值派",
       say="共同基金傳奇經理人，以找「被低估的資產」聞名。他喜歡股價低於淨值（等於打折買公司資產）、經營階層自己持股很多（跟股東站同一邊）、負債又低的公司。",
       rules=["股價淨值比小於 1", "董監持股比率大於 40%", "最近一季負債比小於 20%"]),
  # ---- 新生代大師(依本人公開著作、訪談、股東信歸納的簡化條件,非本人推薦) ----
  dict(id="pabrai", name="莫尼斯帕布萊", en="Mohnish Pabrai", tag="Dhandho 低風險高報酬", gen="new", region="國外",
       say="1964 年生，帕布萊投資基金創辦人，著有《下注的本事（The Dhandho Investor）》，曾花 65 萬美元與巴菲特共進午餐。他的口訣是「正面我大賺、反面我小賠」：只買簡單好懂、賺錢能力強、幾乎不借錢，而且價格明顯便宜的公司。",
       rules=["本益比小於 12", "近 4 季股東權益報酬率大於 15%", "最近一季負債比小於 40%", "近 4 季自由現金流大於 0"]),
  dict(id="burry", name="麥可貝瑞", en="Michael Burry", tag="《大賣空》深度價值", gen="new", region="國外",
       say="1971 年生，Scion 資產管理創辦人，電影《大賣空》主角原型，2008 年押注次貸崩盤一戰成名。選股偏「冷門、被市場嫌棄、但很會賺現金」的公司：用自由現金流殖利率找便宜貨，同時要財務夠安全。",
       rules=["股價淨值比小於 1.2", "自由現金流殖利率大於 8%", "最新財報流動比率大於 150%", "近 4 季 EPS 大於 0"]),
  dict(id="dorsey", name="派特杜西", en="Pat Dorsey", tag="護城河選股", gen="new", region="國外",
       say="晨星前股票研究總監、Dorsey 資產管理創辦人，著有《護城河投資優勢》。他認為長期贏家要有「別人很難搶走的獲利能力」：股東權益報酬率長年都高、毛利率高、而且年年都賺得到真金白銀的現金。",
       rules=["近 5 年股東權益報酬率每年都大於 15%", "近 4 季毛利率大於 30%", "近 5 年自由現金流每年都大於 0", "本益比小於 25"]),
  dict(id="wood", name="凱西伍德", en="Cathie Wood", tag="顛覆式創新", gen="new", region="國外",
       say="方舟投資（ARK Invest）創辦人，被稱為「木頭姐」，專買 AI、機器人、基因、區塊鏈等顛覆式創新公司。她看的是未來 5 年的爆發力而不是現在的本益比，所以條件重成長、重毛利，波動也最大。",
       rules=["近 3 年營收成長率平均大於 25%", "近 4 季營收比上一年度成長 20% 以上", "近 4 季毛利率大於 35%"]),
  dict(id="raohs", name="雷浩斯", en="Lei Haosi", tag="台灣價值投資", gen="new", region="台灣",
       say="台灣價值投資作家，著有《雷浩斯教你 6 步驟存好股》等書，強調「好公司＋好價格」。他用股東權益報酬率長期穩定在高檔來找好公司，再用自由現金流檢查賺的是不是真錢，並避開借太多錢的公司。",
       rules=["近 5 年股東權益報酬率每年都大於 15%", "近 5 年營業現金流每年都大於 0", "近 5 年自由現金流合計大於 0", "最近一季負債比小於 50%", "本益比小於 20"]),
  dict(id="mj", name="林明樟（MJ 老師）", en="MJ Lin", tag="財報現金流檢查", gen="new", region="台灣",
       say="兩岸知名財報講師，著有《用生活常識就能看懂財務報表》。他教大家用現金流量表抓「真賺錢」的公司：營業現金流要大於帳上獲利、本業利潤率要夠高、股東權益報酬率要好，財務結構也要穩。",
       rules=["近 5 年營業現金流合計大於稅後淨利（比率大於 100%）", "近 4 季營業利益率大於 10%", "近 4 季股東權益報酬率大於 15%", "最近一季負債比小於 50%"]),
  dict(id="chenzm", name="陳重銘", en="Chen Chung-Ming", tag="不敗教主存股", gen="new", region="台灣",
       say="人稱「不敗教主」，前高職老師，靠存股累積上千張股票，著有《6 年存到 300 張股票》等書。他的存股原則是：公司要年年賺錢、年年發現金股利，殖利率夠高，用股利再買股讓資產像滾雪球。",
       rules=["近 5 年每年都發現金股利", "現金殖利率大於 5%", "近 5 年每年 EPS 都大於 0 元", "近 5 年平均配息率小於 90%"]),
  dict(id="warrentw", name="華倫老師（周文偉）", en="Warren Chou", tag="ROE 存股法", gen="new", region="台灣",
       say="台灣知名存股達人，從負債到資產破億，著有《華倫存股術》系列。他用「股東權益報酬率長期大於 15% 的好公司＋本益比便宜時買進＋領股利再投入」，強調要挑能長期穩定賺錢、穩定配息的公司。",
       rules=["近 5 年平均股東權益報酬率大於 15%", "近 4 季股東權益報酬率大於 15%", "近 5 年每年都發現金股利", "本益比小於 15"]),
]
NEW_RULE_NOTE = "新生代大師條件依其公開著作、訪談與股東信歸納為可量化的簡化版本，非本人推薦或背書"

def divs():
    p = os.path.join(DATA, "stock_div.json")
    return json.load(open(p))["stocks"] if os.path.exists(p) else {}

def main():
    dpct = director_pct(); DV = divs(); FIX = shares.par_fix(F["companies"])
    stocks, passn = {}, {e["id"]: 0 for e in EXPERTS}
    for c, d in F["companies"].items():
        t = d.get("ttm") or {}; px = d.get("px"); vol = d.get("vol5")
        if not px or not t: continue
        eps, rev, pt, gp, op = ser(d, "eps"), ser(d, "rev"), ser(d, "pt"), ser(d, "gp"), ser(d, "op")
        cap = t.get("cap"); sh = FIX.get(c) or (cap * 100 if cap else None)   # 股本(仟元)→股數;非 10 元面額用實際發行股數
        if c in FIX:   # 面額變更前的每股數字會失真:EPS 改用 淨利 ÷ 目前股數
            t = dict(t, eps=t["niP"] * 1000 / sh if t.get("niP") is not None else None)
            eps = [((d["y"].get(y) or {}).get("niP") or 0) * 1000 / sh if (d["y"].get(y) or {}).get("niP") is not None else None for y in Y]
        bvps = t["eqP"] * 1000 / sh if sh and t.get("eqP") else None
        pe = px / t["eps"] if t.get("eps") and t["eps"] > 0 else None
        pb = px / bvps if bvps and bvps > 0 else None
        roe = ratio(t.get("niP"), t.get("eqP"))
        last = d["y"].get(Y[-1]) or {}; roe0 = ratio(last.get("niP"), last.get("eqP"))
        roeUp = g(roe, roe0) if roe0 and roe0 > 0 else None
        debt = ratio(t.get("tl"), t.get("ta")); cur = ratio(t.get("ca"), t.get("cl"))
        rps = t["rev"] * 1000 / sh if sh and t.get("rev") else None
        gmY = [ratio(gp[i], rev[i]) for i in range(len(Y))]; omY = [ratio(op[i], rev[i]) for i in range(len(Y))]
        gmT, omT = ratio(t.get("gp"), t.get("rev")), ratio(t.get("op"), t.get("rev"))
        rv2, rv3, rv5 = rates(rev, 2), rates(rev, 3), rates(rev, 5)
        pt5, eps5 = rates(pt, 5), rates(eps, 5)
        dir_ = dpct[c] / sh * 100 if sh and c in dpct else None
        # 新生代大師用:現金流、ROE 歷年、股利
        niP, eqP, cfo, cfi = ser(d, "niP"), ser(d, "eqP"), ser(d, "cfo"), ser(d, "cfi")
        roeY = [ratio(niP[i], eqP[i]) if eqP[i] and eqP[i] > 0 else None for i in range(len(Y))]
        fcfY = [cfo[i] + cfi[i] if cfo[i] is not None and cfi[i] is not None else None for i in range(len(Y))]
        fcfT = t["cfo"] + t["cfi"] if t.get("cfo") is not None and t.get("cfi") is not None else None
        mcap = px * sh if sh else None
        fcfYld = fcfT * 1000 / mcap * 100 if fcfT is not None and mcap else None
        r5, f5, c5, n5 = roeY[-5:], fcfY[-5:], cfo[-5:], niP[-5:]
        cfoNi5 = sum(c5) / sum(n5) * 100 if all(x is not None for x in c5 + n5) and sum(n5) > 0 else None
        dy = (DV.get(c) or {}).get("y", {}); cash5 = [(dy.get(y) or {}).get("cash") for y in Y[-5:]]; pay5 = [(dy.get(y) or {}).get("pay") for y in Y[-5:]]
        le = dy.get(Y[-1]) or {}; lastCash = le["tot"] / sh if c in FIX and le.get("tot") and sh else le.get("cash")
        yld = lastCash / px * 100 if lastCash and px else None
        payAvg = avg([x for x in pay5 if x is not None]) if any(x is not None for x in pay5) else None
        revTg = g(t.get("rev"), last.get("rev")) if last.get("rev") else None
        m = dict(pe=R(pe, 1), pb=R(pb, 2), roe=R(roe, 1), roeUp=R(roeUp, 1), debt=R(debt, 1), cur=R(cur, 0), rps=R(rps, 2), rev12=R(t.get("rev") / 1e5 if t.get("rev") else None, 1),
                 revG2=R(avg(rv2), 1), revG3=R(avg(rv3), 1), revG5=R(avg(rv5), 1), revMin5=R(min(rv5), 1) if rv5 else None,
                 ptG5=R(avg(pt5), 1), ptMin5=R(min(pt5), 1) if pt5 else None, epsG5=R(avg(eps5), 1),
                 epsMin5=R(min(x for x in eps[-5:]), 2) if all(x is not None for x in eps[-5:]) else None,
                 gmMin5=R(min(gmY[-5:]), 1) if all(x is not None for x in gmY[-5:]) else None, gm=R(gmT, 1),
                 omMin3=R(min(omY[-3:]), 1) if all(x is not None for x in omY[-3:]) else None, om=R(omT, 1), dir=R(dir_, 1),
                 roeMin5=R(min(r5), 1) if all(x is not None for x in r5) else None, roe5=R(avg(r5), 1) if all(x is not None for x in r5) else None,
                 fcfYld=R(fcfYld, 1), fcf=R(fcfT / 1e5, 1) if fcfT is not None else None,
                 fcfMin5=R(min(f5) / 1e5, 1) if all(x is not None for x in f5) else None, fcfSum5=R(sum(f5) / 1e5, 1) if all(x is not None for x in f5) else None,
                 cfoMin5=R(min(c5) / 1e5, 1) if all(x is not None for x in c5) else None, cfoNi5=R(cfoNi5, 0),
                 divN5=sum(1 for x in cash5 if x and x > 0), yld=R(yld, 2), payAvg=R(payAvg, 0), revTg=R(revTg, 1))
        ok = lambda v, f: v is not None and f(v)
        test = {
          "lynch": [ok(m["pe"], lambda v: v < 20), ok(m["revG2"], lambda v: v > 25), ok(m["ptG5"], lambda v: v > 7), ok(m["debt"], lambda v: v < 30)],
          "graham": [ok(m["epsMin5"], lambda v: v > 0), ok(m["pe"], lambda v: v < 15), ok(m["rev12"], lambda v: v > 3), ok(m["pb"], lambda v: v < 1.5), ok(m["cur"], lambda v: v > 200), ok(m["ptG5"], lambda v: v > 3)],
          "buffett": [ok(m["epsMin5"], lambda v: v > 1), ok(m["rps"], lambda v: v > 1.5), ok(m["pb"], lambda v: v < 1.5), ok(m["roe"], lambda v: v > 5), ok(m["gmMin5"], lambda v: v > 10)],
          "osh": [ok(m["epsG5"], lambda v: v > 15), ok(m["pe"], lambda v: v < 18), ok(m["roe"], lambda v: v > 18), ok(m["roeUp"], lambda v: v > 15)],
          "murphy": [ok(m["revG3"], lambda v: v > 15), ok(m["roe"], lambda v: v > 7), ok(m["om"], lambda v: v > 1), ok(m["omMin3"], lambda v: v > 3)],
          "kfisher": [ok(m["revG5"], lambda v: v > 15), ok(m["ptG5"], lambda v: v > 5), ok(m["debt"], lambda v: v < 30)],
          "yusko": [ok(m["ptMin5"], lambda v: v > 5), ok(m["ptG5"], lambda v: v > 10), ok(m["gm"], lambda v: v > 4)],
          "sivy": [ok(m["pe"], lambda v: v < 20), ok(m["revMin5"], lambda v: v > 10), ok(m["roe"], lambda v: v > 15), ok(m["debt"], lambda v: v < 20)],
          "price": [ok(m["pb"], lambda v: v < 1), ok(m["dir"], lambda v: v > 40), ok(m["debt"], lambda v: v < 20)],
          "pabrai": [ok(m["pe"], lambda v: v < 12), ok(m["roe"], lambda v: v > 15), ok(m["debt"], lambda v: v < 40), ok(m["fcf"], lambda v: v > 0)],
          "burry": [ok(m["pb"], lambda v: v < 1.2), ok(m["fcfYld"], lambda v: v > 8), ok(m["cur"], lambda v: v > 150), ok(t.get("eps"), lambda v: v > 0)],
          "dorsey": [ok(m["roeMin5"], lambda v: v > 15), ok(m["gm"], lambda v: v > 30), ok(m["fcfMin5"], lambda v: v > 0), ok(m["pe"], lambda v: v < 25)],
          "wood": [ok(m["revG3"], lambda v: v > 25), ok(m["revTg"], lambda v: v > 20), ok(m["gm"], lambda v: v > 35)],
          "raohs": [ok(m["roeMin5"], lambda v: v > 15), ok(m["cfoMin5"], lambda v: v > 0), ok(m["fcfSum5"], lambda v: v > 0), ok(m["debt"], lambda v: v < 50), ok(m["pe"], lambda v: v < 20)],
          "mj": [ok(m["cfoNi5"], lambda v: v > 100), ok(m["om"], lambda v: v > 10), ok(m["roe"], lambda v: v > 15), ok(m["debt"], lambda v: v < 50)],
          "chenzm": [m["divN5"] >= 5, ok(m["yld"], lambda v: v > 5), ok(m["epsMin5"], lambda v: v > 0), ok(m["payAvg"], lambda v: v < 90)],
          "warrentw": [ok(m["roe5"], lambda v: v > 15), ok(m["roe"], lambda v: v > 15), m["divN5"] >= 5, ok(m["pe"], lambda v: v < 15)],
        }
        liquid = px >= 5 and (vol or 0) >= 500
        hit = [e["id"] for e in EXPERTS if liquid and all(test[e["id"]])]
        for h in hit: passn[h] += 1
        # 每位大師各條件是否通過(1/0),給網頁顯示「差哪一條」
        stocks[c] = dict(n=d["name"], ind=d.get("ind"), mkt=d.get("mkt"), px=px, vol=vol, liq=int(liquid), hit=hit,
                         t={k: "".join("1" if x else "0" for x in v) for k, v in test.items()}, **m)
    for e in EXPERTS: e["n"] = passn[e["id"]]
    out = dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), ttm=F.get("latest"), years=f"{Y[0]}~{Y[-1]}",
               source="經典大師條件參考 MoneyDJ 大師選股；" + NEW_RULE_NOTE + "；財報來自公開資訊觀測站", filter="排除股價 5 元以下、五日均量 500 張以下", experts=EXPERTS, stocks=stocks)
    fh.save(os.path.join(DATA, "experts.json"), out)
    # 自選股體質追蹤用的精簡檔:每檔目前被哪些大師選中
    nm = {e["id"]: e["name"] for e in EXPERTS}
    fh.save(os.path.join(DATA, "expert_hits.json"), dict(updated=out["updated"], names=nm, h={c: v["hit"] for c, v in stocks.items() if v["hit"]}))
    print("experts.json:", "、".join(f"{e['name']} {e['n']}" for e in EXPERTS), f"(共 {len(stocks)} 家)")

if __name__ == "__main__":
    main()
