"""券商評等/目標價 -> data/ratings.json(只存標題、日期、連結與從標題解析出的數字;內文請點原文)
來源:鉅亨網台股新聞(含 FactSet 法人共識目標價速報)、Yahoo 股市 RSS
每次抓最新的新聞併入歷史,保留近 120 天
"""
import json, os, re, sys, html, time, datetime as dt, urllib.request, email.utils
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; OUT = os.path.join(DATA, "ratings.json")
UA = {"User-Agent": "Mozilla/5.0"}
BROKERS = ["摩根士丹利", "大摩", "摩根大通", "小摩", "高盛", "美銀證券", "美銀", "美林", "花旗", "瑞銀", "野村", "麥格理", "匯豐", "里昂", "巴克萊", "德意志", "德銀", "大和", "瑞穗", "傑富瑞", "伯恩斯坦", "Bernstein",
           "凱基", "元大", "富邦", "國泰", "群益", "統一", "永豐", "兆豐", "中信", "玉山", "第一金", "華南", "新光", "宏遠", "康和", "台新", "日盛",
           "美系外資", "日系外資", "歐系外資", "港系外資", "外資", "本土投顧", "投顧", "法人"]
BULL = r"買進|加碼|優於大盤|增持|看多|喊進|強力買進|看好|樂觀|跑贏"
NEUT = r"中立|持有|區間操作|觀望|中性"
BEAR = r"賣出|減碼|劣於大盤|看空|看淡|跑輸|保守"

def jget(u):
    try: return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40).read())
    except Exception as e: print("  失敗", u[:70], e); return None

def names():
    F = json.load(open(os.path.join(DATA, "fund", "fundamentals.json")))["companies"]
    m = {d["name"]: c for c, d in F.items() if d.get("name") and len(d["name"]) >= 2}
    return m, {c: d.get("px") for c, d in F.items()}, {c: d.get("name") for c, d in F.items()}

def parse(title, NM):
    t = title.replace("　", " ")
    m = re.search(r"Factset 最新調查：(.+?)\((\d{4,6})-TW\)目標價(調升|調降)至([\d.]+)元，幅度約([\d.]+)%", t)
    if m: return dict(id=m[2], src="FactSet 共識", act="調升目標價" if m[3] == "調升" else "調降目標價", tp=float(m[4]), chg=float(m[5]) * (1 if m[3] == "調升" else -1), r="未標示")
    m = re.search(r"Factset 最新調查：(.+?)\((\d{4,6})-TW\)EPS預估(上修|下修)至([\d.]+)元，預估目標價為([\d.]+)元", t)
    if m: return dict(id=m[2], src="FactSet 共識", act="EPS 預估" + m[3], eps=float(m[4]), tp=float(m[5]), r="未標示")
    if "目標價" not in t: return None
    tp = re.search(r"目標價(?:大幅)?(?:上看|調升至|調降至|拉高至|下修至|上修至|調高至|調低至|喊|至|為|到|直指|調升|調降|上調至|下調至)?\s*(\d[\d,]*(?:\.\d+)?)\s*元", t)
    if not tp: return None
    code = None; m = re.search(r"\((\d{4})\)|（(\d{4})）", t)
    if m: code = m[1] or m[2]
    if not code:
        # 公司名後面接「大單、訂單、概念、供應鏈、客戶…」時,標題主角是別家公司(例:吃下台積電大單 這大廠目標價…)
        hit = sorted([n for n in NM if n in t and not re.search(re.escape(n) + r"(?:的)?(?:大單|訂單|轉單|概念|供應鏈|大客戶|客戶|夥伴|合作|效應|帶動|加持)", t)], key=len, reverse=True)
        if not hit or re.search(r"這(?:家|檔|大)?廠|這家公司|這檔|此檔|1檔|一檔|小金雞|神秘", t) and len(hit) == 1 and re.search(re.escape(hit[0]) + r"(?:的)?(?:大單|訂單|轉單|概念|供應鏈|客戶)", title): return None
        code = NM[hit[0]]
    br = next((b for b in BROKERS if b in t), "法人")
    br = {"大摩": "摩根士丹利", "小摩": "摩根大通", "美銀": "美銀證券", "德銀": "德意志"}.get(br, br)
    r = "看多" if re.search(BULL, t) else "看空" if re.search(BEAR, t) else "中立" if re.search(NEUT, t) else "未標示"
    act = "調升目標價" if re.search(r"調升|上修|拉高|調高|上調|大升", t) else "調降目標價" if re.search(r"調降|下修|調低|下調|砍", t) else "首次評等" if re.search(r"首評|首次|初評", t) else "維持"
    return dict(id=code, src=br, act=act, tp=float(tp[1].replace(",", "")), r=r)

def sane(r, PX):
    """目標價離現價太遠(低於 1/3 或超過 3.5 倍)多半是標題解析錯公司,不收"""
    px = PX.get(r["id"]); tp = r.get("tp")
    return not (px and tp) or 0.33 <= tp / px <= 3.5

def main():
    NM, PX, NAME = names()
    old = json.load(open(OUT)) if os.path.exists(OUT) else {"items": []}
    have = {x["k"] for x in old["items"]}; items = old["items"]; add = 0
    news = []
    for p in range(1, 31):                                  # 鉅亨台股新聞(約 2~3 週)
        d = jget(f"https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?limit=30&page={p}")
        if not d or not d.get("items", {}).get("data"): break
        for x in d["items"]["data"]:
            news.append(dict(k="cnyes:%s" % x["newsId"], t=x["title"], ts=x["publishAt"], u=f"https://news.cnyes.com/news/id/{x['newsId']}", s="鉅亨網"))
        time.sleep(.6)
    for cat in ("tw-market", "research", "intl-markets"):    # Yahoo 股市 RSS
        try: xml = urllib.request.urlopen(urllib.request.Request(f"https://tw.stock.yahoo.com/rss?category={cat}", headers=UA), timeout=30).read().decode("utf-8", "ignore")
        except Exception as e: print("  RSS 失敗", cat, e); continue
        for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
            g = lambda tag: (re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", it, re.S) or [None, ""])[1].strip()
            try: ts = int(email.utils.parsedate_to_datetime(g("pubDate")).timestamp())
            except Exception: ts = 0
            src = re.match(r"\s*\[([^\]]{1,20})\]", html.unescape(g("description")))
            news.append(dict(k="yahoo:" + g("link")[-40:], t=html.unescape(g("title")), ts=ts, u=g("link"), s=src[1] if src else "Yahoo股市"))
    for n in news:
        if n["k"] in have or not n["ts"]: continue
        r = parse(n["t"], NM)
        if not r or r["id"] not in NAME: continue
        if not sane(r, PX): continue
        items.append(dict(k=n["k"], d=dt.datetime.fromtimestamp(n["ts"]).strftime("%Y-%m-%d"), n=NAME[r["id"]], title=n["t"], u=n["u"], media=n["s"], **r))
        have.add(n["k"]); add += 1
    cut = (dt.date.today() - dt.timedelta(days=120)).isoformat()
    items = [x for x in items if x["d"] >= cut and sane(x, PX)]; items.sort(key=lambda x: (x["d"], x["k"]), reverse=True)
    fh.save(OUT, dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), px={x["id"]: PX.get(x["id"]) for x in items}, items=items,
                      note="整理自公開新聞標題，每筆附原文連結；評等以標題文字判斷，FactSet 為多家法人預估的共識值。"))
    print(f"ratings.json:新增 {add} 筆,共 {len(items)} 筆({len({x['id'] for x in items})} 檔)")

if __name__ == "__main__":
    main()
