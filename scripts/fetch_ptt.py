"""PTT 股版熱度 -> data/ptt.json
抓 PTT Stock 板最新約 20 頁文章「標題」(不抓內文、不抓帳號),統計:
  被提到最多次的股票(代號或公司名)、[標的] 文的多空方向、推文熱度(列表上的推文數)
社群討論熱度只是「大家在聊什麼」,不代表會漲;常常是過熱的反指標
"""
import json, os, re, sys, html, time, datetime as dt, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; BASE = "https://www.ptt.cc"
SKIP = {"台灣", "中華", "統一", "國泰", "富邦", "永豐", "元大", "華南", "第一", "大同", "聯發", "新光", "台新", "群益", "宏達", "光寶", "日盛", "凱基", "玉山", "合庫", "兆豐", "中信", "遠東", "三星", "大成", "華新", "東元", "全新", "聯合", "亞洲", "世界", "光明", "永大", "正新", "國產"}  # 太常見、容易誤判的短名

def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Cookie": "over18=1"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")

def main(pages=20):
    names = json.load(open(os.path.join(DATA, "names.json")))
    stocks = [(r[0], r[1]) for r in names if r[3] in ("上市", "上櫃") and len(r[0]) == 4 and not r[0].startswith("00")]
    byname = {n.replace("*", "").split("-")[0]: c for c, n in stocks}
    name_re = re.compile("|".join(sorted((re.escape(n) for n in byname if len(n) >= 2 and n not in SKIP), key=len, reverse=True)))
    codes = {c for c, _ in stocks}; nm = dict(stocks)
    url, posts = BASE + "/bbs/Stock/index.html", []
    for _ in range(pages):
        try: h = get(url)
        except Exception as e: print("  PTT 失敗", e); break
        for blk in re.findall(r'<div class="r-ent">([\s\S]*?)</div>\s*</div>\s*</div>', h):
            t = re.search(r'<a href="(/bbs/Stock/M\.[^"]+)">([^<]+)</a>', blk)
            if not t: continue
            nr = re.search(r'<div class="nrec">(?:<span[^>]*>)?([^<]*)', blk); n = (nr[1] if nr else "").strip()
            push = 100 if n == "爆" else (-10 if n.startswith("X") else int(n) if n.isdigit() else 0)
            d = re.search(r'<div class="date">\s*([\d/]+)', blk)
            posts.append(dict(u=BASE + t[1], t=html.unescape(t[2]).strip(), p=push, d=d[1].strip() if d else ""))
        prev = re.search(r'href="(/bbs/Stock/index\d+\.html)">&lsaquo;', h)
        if not prev: break
        url = BASE + prev[1]; time.sleep(.8)
    agg = {}
    for x in posts:
        if "公告" in x["t"]: continue
        nh = {byname[m] for m in name_re.findall(x["t"])}
        # 4 位數字:像年份(1990～2035)的,標題裡要同時出現公司名才算
        hit = {c for c in set(re.findall(r"(?<!\d)(\d{4})(?!\d)", x["t"])) & codes if not (1990 <= int(c) <= 2035) or c in nh} | nh
        bull = bool(re.search(r"\[標的\].*(多|做多|多單)\s*$", x["t"])); bear = bool(re.search(r"\[標的\].*(空|放空|空單)\s*$", x["t"]))
        for c in hit:
            a = agg.setdefault(c, [0, 0, 0, 0]); a[0] += 1; a[1] += int(bull); a[2] += int(bear); a[3] += max(x["p"], 0)
    top = sorted(agg.items(), key=lambda kv: (-kv[1][0], -kv[1][3]))[:40]
    tgt = [x for x in posts if x["t"].startswith("[標的]")][:20]
    if not posts:                                   # PTT 擋雲端主機(403)時:保留上一版,不用空資料蓋掉
        print("ptt.json:這次抓不到 PTT,保留上一版"); return
    fh.save(os.path.join(DATA, "ptt.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), n=len(posts),
            top=[[c, nm.get(c, c)] + v for c, v in top], tgt=tgt, hot=sorted(posts, key=lambda x: -x["p"])[:10],
            cols=["代號", "名稱", "被提到篇數", "標的看多", "標的看空", "推文熱度"],
            note="統計 PTT Stock 板最新文章標題；討論熱度≠會漲，常是過熱的反指標"))
    print("ptt.json:", len(posts), "篇;熱門", [(c, nm.get(c), v[0]) for c, v in top[:5]])

if __name__ == "__main__":
    main()
