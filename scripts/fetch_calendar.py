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
            out.append(dict(d=loc.date().isoformat(), t=loc.strftime("%H:%M"), c="US", n=zh, imp=imp, why=why, prev=prev_of(macro, sid), src="FRED"))
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
        if "Minutes" in tt: out.append(dict(d=loc.date().isoformat(), t=loc.strftime("%H:%M"), c="US", n="🇺🇸 FOMC 會議紀錄", imp="中高", why="看聯準會委員們私下怎麼討論降息升息", prev="", src="Fed"))
        elif "Meeting" in tt: out.append(dict(d=loc.date().isoformat(), t=loc.strftime("%H:%M"), c="US", n="🇺🇸 FOMC 利率決策", imp="極高", why="全世界最重要的利率決定，影響所有股市", prev="", src="Fed"))
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
        add = lambda d, n, imp, why, prev="", t="", approx=True: out.append(dict(d=d.isoformat(), t=t, c="TW", n=n, imp=imp, why=why, prev=prev, approx=approx, src="慣例"))
        add(bizday(dt.date(y, m, 10)), "🇹🇼 上市櫃月營收公布截止", "高", "每家公司上個月生意好不好，台股最重要的月度數據", "", "", False)
        add(nth_wd(y, m, 2, 3), "🇹🇼 台指期／選擇權結算", "高", "期貨和選擇權到期，大戶常在這天前後拉抬或壓低指數", "", "13:30", False)
        add(bizday(dt.date(y, m, 6)), "🇹🇼 消費者物價 CPI（主計總處）", "中", "台灣的通膨", "", "16:00")
        add(bizday(dt.date(y, m, 8)), "🇹🇼 海關出口（財政部）", "高", "台灣靠出口賺錢，出口好股市通常好", f"前值 {ex[-1][1]:+.1f}%" if ex else "", "16:00")
        add(bizday(dt.date(y, m, 20)), "🇹🇼 外銷訂單（經濟部）", "高", "未來 1～3 個月出口的領先指標", f"前值 {ord_[-1][1]:+.1f}%" if ord_ else "", "16:00")
        add(bizday(dt.date(y, m, 27)), "🇹🇼 景氣對策信號（國發會）", "中", "紅黃綠藍燈判斷台灣景氣冷熱", light_prev, "16:00")
        if m in (3, 6, 9, 12): add(nth_wd(y, m, 3, 3), "🇹🇼 央行理監事會（利率決策）", "高", "台灣的利率與房市、匯率政策", "", "16:00")
    return out

def stocks(start, end):
    out = []
    hm = {x[0]: x for x in (L("heatmap.json", {}) or {}).get("items", [])}
    top = {c for c, _ in sorted(((c, x[3] or 0) for c, x in hm.items()), key=lambda z: -z[1])[:100]}
    S = {e["id"]: e for e in (L("summary.json", {}) or {}).get("etfs", [])}
    hotE = {k for k, e in S.items() if (e.get("aum") or 0) > 5e10}
    for u in (L("stock_div.json", {}) or {}).get("up", []) or []:
        if start.isoformat() <= u["d"] <= end.isoformat() and (u["c"] in top or u["c"] in hotE) and u.get("cash"):
            out.append(dict(d=u["d"], t="", c="TW", n=f"💰 {u['c']} {u['n']} 除息 {u['cash']} 元", imp="中", why="除息日前一天持有才領得到", prev="", src="證交所", code=u["c"]))
    top50 = {c for c, _ in sorted(((c, x[3] or 0) for c, x in hm.items()), key=lambda z: -z[1])[:50]}
    byday = {}
    for e in (L("events.json", {}) or {}).get("conf", []) or []:
        if start.isoformat() <= e["d"] <= end.isoformat() and e["c"] in top50:
            byday.setdefault(e["d"], {})[e["c"]] = e["n"]
    for d, cs in byday.items():           # 同一天的大型股法說會合併成一行
        names = "、".join(f"{n}" for c, n in list(cs.items())[:6]) + (f" 等 {len(cs)} 家" if len(cs) > 6 else "")
        out.append(dict(d=d, t="", c="TW", n=f"🎤 大型股法說會：{names}", imp="中", why="公司親自說明營運與展望，股價常波動", prev="", src="公開資訊觀測站", codes=list(cs)))
    return out

def main():
    today = dt.datetime.now(TPE).date(); start, end = today - dt.timedelta(days=7), today + dt.timedelta(days=45)
    macro = L("macro.json", {})
    fr = fred(macro, start, end)
    if not fr:                                   # FRED 抓不到:沿用上次成功的美國經濟數據
        fr = [e for e in (L("calendar.json", {}) or {}).get("ev", []) if e.get("src") == "FRED"]; print("  沿用上次 FRED 事件", len(fr))
    ev = fr + fomc() + taiwan(macro, start, end) + stocks(start, end)
    ev = [e for e in ev if start.isoformat() <= e["d"] <= end.isoformat()]
    seen, out = set(), []
    for e in sorted(ev, key=lambda e: (e["d"], e.get("t") or "99", e["n"])):
        k = (e["d"], e["n"])
        if k in seen: continue
        seen.add(k); out.append(e)
    fh.save(os.path.join(DATA, "calendar.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), ev=out,
            note="美國時間已換算成台北時間；標「約」的台灣日期依官方慣例推算，實際以發布單位公告為準。預測值需付費資料，這裡提供前值。"))
    print("calendar.json:", len(out), "件;", sum(1 for e in out if e["c"] == "US"), "美國 /", sum(1 for e in out if e["c"] == "TW"), "台灣")

if __name__ == "__main__":
    main()
