"""經濟行事曆 -> data/calendar.json(往前 7 天、往後 45 天)
美國:FRED 發布行事曆(勞工統計局 CPI/非農/PPI、普查局零售、BEA GDP/PCE、密大信心…,美國中部時間→台北)、聯準會 FOMC(federalreserve.gov)
台灣:依官方慣例日期推算(標示「約」):主計總處 CPI、財政部出口、經濟部外銷訂單、國發會景氣燈號、央行理監事會;
台股:月營收公布截止(10 日)、台指期/選擇權結算(第 3 個週三)、熱門 ETF 與大型股除息、市值前 100 大公司法說會
"""
import json, os, re, sys, html, calendar, datetime as dt, urllib.request
from zoneinfo import ZoneInfo
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; TPE = ZoneInfo("Asia/Taipei")
L = lambda n, d=None: json.load(open(os.path.join(DATA, n))) if os.path.exists(os.path.join(DATA, n)) else d
# FRED 發布名稱 -> (中文, 重要性, 白話為什麼重要, macro.json 序列代號, 單位)
FRED = {
  "Consumer Price Index": ("🇺🇸 CPI 消費者物價", "極高", "通膨熱不熱，決定聯準會會不會降息", "CPIAUCSL", "%"),
  "Employment Situation": ("🇺🇸 非農就業＋失業率", "極高", "美國找到工作的人多不多，景氣與降息的關鍵", "PAYEMS", "千人"),
  "Personal Income and Outlays": ("🇺🇸 PCE 物價（聯準會最愛）", "極高", "聯準會最看重的通膨指標", "PCEPILFE", "%"),
  "Producer Price Index": ("🇺🇸 PPI 生產者物價", "中", "工廠成本，CPI 的前哨", "PPIFIS", "%"),
  "Advance Monthly Sales for Retail and Food Services": ("🇺🇸 零售銷售", "中", "美國人花錢的力道，占經濟七成", "RSAFS", "%"),
  "Gross Domestic Product": ("🇺🇸 GDP 經濟成長率", "中", "整體經濟成績單", "A191RL1Q225SBEA", "%"),
  "Job Openings and Labor Turnover Survey": ("🇺🇸 JOLTS 職缺", "中", "企業還想不想請人", None, ""),
  "Unemployment Insurance Weekly Claims Report": ("🇺🇸 初領失業救濟金", "中低", "每週最即時的裁員溫度", "ICSA", "人"),
  "Surveys of Consumers": ("🇺🇸 密大消費者信心", "中", "美國人對未來有沒有信心", "UMCSENT", ""),
  "Manufacturing Business Outlook Survey": ("🇺🇸 費城聯準會製造業", "中高", "工廠景氣的領先指標", "GACDFSA066MSFRBPHI", ""),
  "Industrial Production and Capacity Utilization": ("🇺🇸 工業生產", "中", "工廠實際生產多少", None, ""),
}

def get(u, t=90):
    import time
    for k in range(3):                       # FRED 偶爾很慢:重試
        try: return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=t).read().decode("utf-8-sig", "ignore")
        except Exception as e:
            if k == 2: raise
            time.sleep(5 + k * 10)

def prev_of(macro, sid):
    if not sid or not macro: return ""
    s = (macro.get("s") or {}).get(sid);
    if not s or not s.get("rows"): return ""
    v = s["rows"][-1][1]
    if sid == "PAYEMS": return f"前值 {v / 10:+.1f} 萬人"
    if sid == "ICSA": return f"前值 {v / 1e4:.1f} 萬人"
    if sid in ("UMCSENT", "GACDFSA066MSFRBPHI"): return f"前值 {v:.1f}"
    return f"前值 {v:+.2f}%"

def fred(macro, start, end):
    out = []
    months = sorted({(start.year, start.month), (end.year, end.month), ((start + dt.timedelta(days=31)).year, (start + dt.timedelta(days=31)).month)})
    for y, m in months:
        try: h = get(f"https://fred.stlouisfed.org/releases/calendar?y={y}&m={m}&vs={y}-{m:02d}-01&ve={y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}&ob=rd&od=asc")
        except Exception as e: print("  FRED 行事曆失敗", y, m, e); continue
        body = h[h.find("<tbody"):h.find("</tbody>")]
        day = None; tm = None
        for row in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", body):
            dm = re.search(r"font-weight: bold;\">\s*\w+\s+(\w+ \d{1,2}, \d{4})", row)
            if dm: day = dt.datetime.strptime(dm[1], "%B %d, %Y").date(); tm = None; continue
            cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row)
            if len(cells) < 2 or not day: continue
            t = re.sub(r"<[^>]+>|\s+", " ", cells[0]).strip(); name = html.unescape(re.sub(r"<[^>]+>", "", cells[1])).strip()
            if t: tm = t
            if name not in FRED: continue
            hh, mm = 8, 30
            if tm:
                mt = re.match(r"(\d{1,2}):(\d{2})\s*(am|pm)", tm)
                if mt: hh = int(mt[1]) % 12 + (12 if mt[3] == "pm" else 0); mm = int(mt[2])
            loc = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=ZoneInfo("America/Chicago")).astimezone(TPE)
            zh, imp, why, sid, _ = FRED[name]
            out.append(dict(d=loc.date().isoformat(), t=loc.strftime("%H:%M"), c="US", n=zh, imp=imp, why=why, prev=prev_of(macro, sid), src="FRED", key=sid or name))
    return out

def fomc():
    out = []
    try: ev = json.loads(get("https://www.federalreserve.gov/json/calendar.json"))["events"]
    except Exception as e: print("  聯準會行事曆失敗", e); return out
    for e in ev:
        tt = e.get("title", "")
        if e.get("type") != "FOMC" or not e.get("month") or not e.get("days"): continue
        last = int(str(e["days"]).split("-")[-1].strip()); y, m = map(int, e["month"].split("-"))
        hh = 14 if "Meeting" in tt or "Minutes" in tt else 14
        loc = dt.datetime(y, m, last, hh, 0, tzinfo=ZoneInfo("America/New_York")).astimezone(TPE)
        if "Minutes" in tt: out.append(dict(d=loc.date().isoformat(), t=loc.strftime("%H:%M"), c="US", n="🇺🇸 FOMC 會議紀錄", imp="中高", why="看聯準會委員們私下怎麼討論降息升息", prev="", src="Fed", key="MINUTES"))
        elif "Meeting" in tt: out.append(dict(d=loc.date().isoformat(), t=loc.strftime("%H:%M"), c="US", n="🇺🇸 FOMC 利率決策", imp="極高", why="全世界最重要的利率決定，影響所有股市", prev="", src="Fed", key="FOMC"))
    return out

def nth_wd(y, m, wd, n):
    ds = [d for d in range(1, calendar.monthrange(y, m)[1] + 1) if dt.date(y, m, d).weekday() == wd]
    return dt.date(y, m, ds[min(n, len(ds)) - 1])
def bizday(d):
    while d.weekday() >= 5: d += dt.timedelta(days=1)
    return d

def taiwan(macro, start, end):
    out = []; tw = (macro or {}).get("tw") or {}
    tl = lambda k: (tw.get(k) or {}).get("rows") or []
    lt = tl("LIGHT"); light_prev = f"前值 {tw['LIGHT'].get('last_color', '')}燈 {lt[-1][1]:.0f} 分" if lt else ""
    ex = tl("EXPORT"); ord_ = tl("ORDERS")
    m0 = dt.date(start.year, start.month, 1)
    for k in range(3):
        y, m = (m0.year + (m0.month - 1 + k) // 12), (m0.month - 1 + k) % 12 + 1
        add = lambda d, n, imp, why, prev="", t="", approx=True, key="": out.append(dict(d=d.isoformat(), t=t, c="TW", n=n, imp=imp, why=why, prev=prev, approx=approx, src="慣例", key=key))
        add(bizday(dt.date(y, m, 10)), "🇹🇼 上市櫃月營收公布截止", "高", "每家公司上個月生意好不好，台股最重要的月度數據", "", "", False, key="REV")
        add(nth_wd(y, m, 2, 3), "🇹🇼 台指期／選擇權結算", "高", "期貨和選擇權到期，大戶常在這天前後拉抬或壓低指數", "", "13:30", False, key="SETTLE")
        add(bizday(dt.date(y, m, 6)), "🇹🇼 消費者物價 CPI（主計總處）", "中", "台灣的通膨", "", "16:00", key="TWCPI")
        add(bizday(dt.date(y, m, 8)), "🇹🇼 海關出口（財政部）", "高", "台灣靠出口賺錢，出口好股市通常好", f"前值 {ex[-1][1]:+.1f}%" if ex else "", "16:00", key="EXPORT")
        add(bizday(dt.date(y, m, 20)), "🇹🇼 外銷訂單（經濟部）", "高", "未來 1～3 個月出口的領先指標", f"前值 {ord_[-1][1]:+.1f}%" if ord_ else "", "16:00", key="ORDERS")
        add(bizday(dt.date(y, m, 27)), "🇹🇼 景氣對策信號（國發會）", "中", "紅黃綠藍燈判斷台灣景氣冷熱", light_prev, "16:00", key="LIGHT")
        if m in (3, 6, 9, 12): add(nth_wd(y, m, 3, 3), "🇹🇼 央行理監事會（利率決策）", "高", "台灣的利率與房市、匯率政策", "", "16:00", key="CBC")
    return out

def stocks(start, end):
    out = []
    hm = {x[0]: x for x in (L("heatmap.json", {}) or {}).get("items", [])}
    top = {c for c, _ in sorted(((c, x[3] or 0) for c, x in hm.items()), key=lambda z: -z[1])[:100]}
    S = {e["id"]: e for e in (L("summary.json", {}) or {}).get("etfs", [])}
    hotE = {k for k, e in S.items() if (e.get("aum") or 0) > 5e10}
    for u in (L("stock_div.json", {}) or {}).get("up", []) or []:
        if start.isoformat() <= u["d"] <= end.isoformat() and (u["c"] in top or u["c"] in hotE) and u.get("cash"):
            out.append(dict(d=u["d"], t="", c="TW", n=f"💰 {u['c']} {u['n']} 除息 {u['cash']} 元", imp="中", why="除息日前一天持有才領得到", prev="", src="證交所", code=u["c"], key="EXDIV"))
    top50 = {c for c, _ in sorted(((c, x[3] or 0) for c, x in hm.items()), key=lambda z: -z[1])[:50]}
    byday = {}
    for e in (L("events.json", {}) or {}).get("conf", []) or []:
        if start.isoformat() <= e["d"] <= end.isoformat() and e["c"] in top50:
            byday.setdefault(e["d"], {})[e["c"]] = e["n"]
    for d, cs in byday.items():           # 同一天的大型股法說會合併成一行
        names = "、".join(f"{n}" for c, n in list(cs.items())[:6]) + (f" 等 {len(cs)} 家" if len(cs) > 6 else "")
        out.append(dict(d=d, t="", c="TW", n=f"🎤 大型股法說會：{names}", imp="中", why="公司親自說明營運與展望，股價常波動", prev="", src="公開資訊觀測站", codes=list(cs), key="CONF"))
    return out

# ---------- 休市、提早收盤、夏令時間 ----------
def easter(y):
    a, b, c = y % 19, y // 100, y % 100; d, e = b // 4, b % 4; f = (b + 8) // 25; g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30; i, k = c // 4, c % 4; l = (32 + 2 * e + 2 * i - h - k) % 7; m = (a + 11 * h + 22 * l) // 451
    mo = (h + l - 7 * m + 114) // 31; return dt.date(y, mo, (h + l - 7 * m + 114) % 31 + 1)
def obs(d):                                   # 週六→週五、週日→週一
    return d - dt.timedelta(days=1) if d.weekday() == 5 else d + dt.timedelta(days=1) if d.weekday() == 6 else d
def last_wd(y, m, wd):
    d = dt.date(y, m, calendar.monthrange(y, m)[1])
    while d.weekday() != wd: d -= dt.timedelta(days=1)
    return d
def us_market(y):
    """紐約證交所休市日與提早收盤(下午 1 點收,台北凌晨 2 點/3 點)"""
    H = []
    nd = dt.date(y, 1, 1)
    if nd.weekday() != 5: H.append((obs(nd), "🎆 元旦｜美股休市"))
    H += [(nth_wd(y, 1, 0, 3), "🇺🇸 馬丁路德金恩紀念日｜美股休市"), (nth_wd(y, 2, 0, 3), "🇺🇸 總統日｜美股休市"), (easter(y) - dt.timedelta(days=2), "✝️ 耶穌受難日｜美股休市"),
          (last_wd(y, 5, 0), "🇺🇸 陣亡將士紀念日｜美股休市"), (obs(dt.date(y, 6, 19)), "🇺🇸 六月節｜美股休市"), (obs(dt.date(y, 7, 4)), "🎆 美國獨立紀念日｜美股休市"),
          (nth_wd(y, 9, 0, 1), "🇺🇸 勞動節｜美股休市"), (nth_wd(y, 11, 3, 4), "🦃 感恩節｜美股休市"), (obs(dt.date(y, 12, 25)), "🎄 聖誕節｜美股休市")]
    E = [(nth_wd(y, 11, 3, 4) + dt.timedelta(days=1), "🍂 感恩節翌日｜美股提早收盤")]
    if dt.date(y, 12, 24).weekday() < 5 and obs(dt.date(y, 12, 25)) != dt.date(y, 12, 24): E.append((dt.date(y, 12, 24), "🎄 平安夜｜美股提早收盤"))
    j4 = dt.date(y, 7, 4)
    if 1 <= j4.weekday() <= 4: E.append((j4 - dt.timedelta(days=1), "🎆 獨立紀念日前夕｜美股提早收盤"))
    out = [dict(d=d.isoformat(), t="", c="US", n=n, imp="中", why="美國股市這天不開盤，全球資金比較安靜", prev="", src="規則", key="USHOL") for d, n in H]
    for d, n in E:
        close = dt.datetime(d.year, d.month, d.day, 13, 0, tzinfo=ZoneInfo("America/New_York")).astimezone(TPE)
        out.append(dict(d=d.isoformat(), t="", c="US", n=n + f"（台北隔天 {close.strftime('%H:%M')} 收）", imp="中低", why="美股只交易半天，交易清淡", prev="", src="規則", key="USHALF"))
    for d, n in ((nth_wd(y, 3, 6, 2), "🕐 美股改夏令時間：開盤改台北 21:30、收盤 04:00"), (nth_wd(y, 11, 6, 1), "🕐 美股改冬令時間：開盤改台北 22:30、收盤 05:00")):
        out.append(dict(d=d.isoformat(), t="", c="US", n=n, imp="中低", why="美股的台北交易時間會差一小時", prev="", src="規則", key="DST"))
    return out
def tw_market():
    out = []
    try:
        rows = json.loads(get("https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"))
    except Exception as e: print("  台股休市日失敗", e); rows = []
    for r in rows:
        d = r.get("Date", ""); n = r.get("Name", "")
        if len(d) != 7: continue
        dd = f"{int(d[:3]) + 1911}-{d[3:5]}-{d[5:]}"
        if "開始交易" in n: out.append(dict(d=dd, t="09:00", c="TW", n=f"🧧 {n}（開紅盤）", imp="中", why="長假後第一天開市，假期間的國際消息會一次反映", prev="", src="證交所", key="TWOPEN"))
        elif "最後交易" in n: out.append(dict(d=dd, t="13:30", c="TW", n=f"🔒 {n}（封關）", imp="中", why="長假前最後一天交易，有人會先賣出避開假期風險", prev="", src="證交所", key="TWCLOSE"))
        elif "無交易" in n: out.append(dict(d=dd, t="", c="TW", n="🚫 台股無交易（僅辦理結算交割）", imp="中低", why="市場不開盤", prev="", src="證交所", key="TWHOL"))
        else: out.append(dict(d=dd, t="", c="TW", n=f"🚫 {n}｜台股休市", imp="中", why="台股不開盤", prev="", src="證交所", key="TWHOL"))
    return out

# ---------- 每個事件的「可能動向與影響」----------
def assess(ev, macro, ctx):
    s = (macro or {}).get("s") or {}; tw = (macro or {}).get("tw") or {}
    def trend(sid, n=3, src=s):
        r = (src.get(sid) or {}).get("rows") or []
        v = [x[1] for x in r[-n:] if x[1] is not None]
        return (v[-1], v[-1] - v[0]) if len(v) >= 2 else (v[-1] if v else None, 0)
    k = ev.get("key", "")
    def put(dir_, eff): ev["dir"], ev["eff"] = dir_, eff
    if k in ("CPIAUCSL", "PCEPILFE", "PPIFIS"):
        v, ch = trend(k)
        if v is None: return put("看數據", "公布值高於前值偏空、低於前值偏多。")
        lean = "通膨近幾個月在升溫" if ch > .1 else "通膨近幾個月在降溫" if ch < -.1 else "通膨近幾個月持平"
        put("偏空風險" if ch > .1 or v > 3 else "看數據", f"{lean}（最新 {v:.2f}%）。若公布值再高於前值 → 降息機會變小，科技股、成長股容易跌（偏空）；若低於前值 → 降息預期升溫，股市偏多。公布當晚美股、隔天台股波動會加大。")
    elif k == "PAYEMS":
        v, ch = trend("PAYEMS"); u, uch = trend("UNRATE")
        put("看數據", f"上次新增 {v / 10:+.1f} 萬人、失業率 {u if u is not None else 0:.1f}%。就業太強 → 怕聯準會不降息（偏空）；太弱 → 怕景氣衰退（也偏空）；溫和最好。這份數據常讓美股單日大漲大跌。" if v is not None else "就業太強或太弱都可能讓股市波動。")
    elif k in ("FOMC", "MINUTES"):
        fed = (macro or {}).get("fed") or []; last = fed[-1] if fed else None
        txt = f"上次（{last['d']}）{'升' if last['bp'] > 0 else '降'}息 {abs(last['bp']) / 25:.0f} 碼。" if last else ""
        if k == "FOMC": put("波動大", txt + "若再升息或暗示不降息 → 偏空；若維持不變並釋出降息訊號 → 偏多。決策在台北凌晨公布，隔天台股開盤直接反應，持股可先降低槓桿。")
        else: put("中性", txt + "會議紀錄會透露委員們的真實想法，若偏鷹（想升息）美股容易回檔。")
    elif k in ("A191RL1Q225SBEA", "Advance Monthly Sales for Retail and Food Services", "RSAFS", "UMCSENT", "Surveys of Consumers", "GACDFSA066MSFRBPHI", "ICSA"):
        put("看數據", "數據比預期好 → 景氣強、股市偏多，但太強會讓降息延後；比預期差 → 擔心衰退。單一數據影響通常一兩天。")
    elif k == "USHOL":
        put("量縮", "美股休市，台股少了美股指引，外資動作通常較小、成交量偏少；隔天美股恢復交易時會一次反映休市期間的消息。")
    elif k == "USHALF":
        put("量縮", "美股只開半天、交易清淡，容易出現小幅漲跌；年底節慶期間常有「聖誕行情」的說法，但不保證。")
    elif k == "DST":
        put("中性", "只影響美股在台灣時間的開收盤時間，不影響漲跌。夜盤看美股的時間要跟著調整。")
    elif k == "SETTLE":
        o = (ctx.get("opt") or {}).get("oi") or {}; m = o.get("month") or {}
        lv = f"目前月選最大未平倉：壓力 {m['call'][0][0]:,.0f}、支撐 {m['put'][0][0]:,.0f}。" if m.get("call") and m.get("put") else ""
        put("波動大", lv + "結算日前後大戶常把指數拉向對自己有利的價位，台指期與現貨波動加大；結算後新的月份重新布局。")
    elif k == "REV":
        r = ctx.get("revUp"); put("偏多" if r and r >= 55 else "偏空" if r and r < 45 else "中性",
            (f"上個月有 {r:.0f}% 公司營收年增。" if r else "") + "營收公布前後，成長股看「是否創新高」，創新高的股票常被法人追捧；衰退的會被賣。")
    elif k in ("EXPORT", "ORDERS"):
        v, ch = trend(k, 3, tw)
        put("偏多" if v and v > 10 else "偏空" if v is not None and v < 0 else "中性", f"前一次年增 {v:+.1f}%{'，仍在高成長' if v and v > 10 else ''}。" if v is not None else "" + "出口、訂單是台灣企業獲利的前哨，持續成長對電子股有利；若成長大幅放緩，市場會擔心景氣見頂。")
    elif k == "LIGHT":
        lt = (tw.get("LIGHT") or {}); c = lt.get("last_color", ""); r = lt.get("rows") or []; v = r[-1][1] if r else None
        put("中性" if c == "紅" else "偏多" if c in ("綠", "黃紅") else "偏空", f"上次{c}燈 {v:.0f} 分。" + ("紅燈代表景氣過熱，歷史上紅燈後常是股市高檔區，要留意轉弱。" if c == "紅" else "綠燈景氣穩定；藍燈雖然景氣差，但常是長線布局時機。") if v else "景氣燈號反映整體景氣冷熱。")
    elif k == "TWCPI":
        put("中性", "台灣通膨影響央行利率政策，對股市影響通常比美國 CPI 小。")
    elif k == "CBC":
        put("中性", "央行升息 → 房市、金融股受影響；不動利率通常影響不大。也會宣布打房、匯率相關措施。")
    elif k == "EXDIV":
        put("中性", "除息當天股價會先扣掉股利；高股息 ETF 除息前常有「搶息」買盤，除息後看能不能填息。")
    elif k == "CONF":
        put("波動大", "法說會公布營運展望與財測，好於預期隔天大漲、低於預期大跌；持股者可先看法說會簡報再決定。")
    elif k == "TWCLOSE":
        f = ctx.get("fi5"); put("量縮", (f"外資近 5 日{'買超' if f and f > 0 else '賣超'} {abs(f):,.0f} 億。" if f is not None else "") + "封關前有人會先賣股避開假期國際風險，成交量偏少；長假期間的國際消息會在開紅盤一次反映。")
    elif k == "TWOPEN":
        put("波動大", "長假後第一天開市，會一次反映假期間美股與國際消息；先看假期間美股漲跌，大致可推估開盤方向。")
    elif k == "TWHOL":
        put("中性", "台股休市；台指期夜盤與國際股市照常，回來開盤時一次反映。")

def main():
    today = dt.datetime.now(TPE).date(); start, end = today - dt.timedelta(days=7), today + dt.timedelta(days=45)
    macro = L("macro.json", {})
    fr = fred(macro, start, end)
    if not fr:                                   # FRED 抓不到:沿用上次成功的美國經濟數據
        fr = [e for e in (L("calendar.json", {}) or {}).get("ev", []) if e.get("src") == "FRED"]; print("  沿用上次 FRED 事件", len(fr))
    hol = us_market(today.year) + us_market(today.year + 1) + tw_market()
    ev = fr + fomc() + taiwan(macro, start, end) + stocks(start, end) + hol
    opt = L("options.json", {}) or {}; rv = (L("rev_rank.json", {}) or {}).get("stocks", {}); inst = (L("inst.json", {}) or {}).get("twse") or {}
    ys = [x[4] for x in rv.values() if x[4] is not None]
    ctx = dict(opt=opt, revUp=sum(1 for x in ys if x > 0) / len(ys) * 100 if ys else None, fi5=inst.get("fi5"))
    for e in ev: assess(e, macro, ctx)
    ev = [e for e in ev if start.isoformat() <= e["d"] <= end.isoformat()]
    seen, out = set(), []
    for e in sorted(ev, key=lambda e: (e["d"], e.get("t") or "99", e["n"])):
        k = (e["d"], e["n"])
        if k in seen: continue
        seen.add(k); out.append(e)
    fh.save(os.path.join(DATA, "calendar.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), ev=out,
            note="美國時間已換算成台北時間；標「約」的台灣日期依官方慣例推算，實際以發布單位公告為準。美股休市依紐約證交所規則推算、台股休市來自證交所公告。「可能動向」是依最新數據趨勢的規則判斷，不是預測保證。"))
    print("calendar.json:", len(out), "件;", sum(1 for e in out if e["c"] == "US"), "美國 /", sum(1 for e in out if e["c"] == "TW"), "台灣")

if __name__ == "__main__":
    main()
