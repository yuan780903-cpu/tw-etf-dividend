#!/usr/bin/env python3
"""🛡️ 每週網站自動巡檢＋自動修復(GitHub Actions inspect.yml,每週日台北 10:00;也可手動觸發)
檢查 5 大類,能修的自動修,修不了的寫進 data/inspect.json(網站頁尾「🛡️ 每週巡檢」看得到),仍有嚴重問題就開 GitHub Issue 通知:
  1. 網站本體:首頁打得開、版本號、程式語法(node --check)、實際開網頁有沒有 JS 錯誤(Playwright)、圖示/logo/manifest 等檔案都在
     → 程式語法壞了:自動把 index.html 還原到最近一個語法正常的版本
     → 每月 logo 檔不見:用 tools/gen_logos.py 重新產生
  2. 資料:每日健康報告(health.json)新不新、有沒有錯誤;行事曆有沒有美國/台灣數據日;PTT、總經資料新不新
     → 資料過期或有錯:自動觸發一次完整更新(update.yml full),跑完再檢查一次
     → 行事曆少了美國數據:在這裡直接重抓 fetch_calendar.py
  3. 雲端推播(etf-alert Worker):最近一週每個交易日的晨報/開收盤/三大法人/夜盤/美股摘要有沒有發、排程有沒有在跑、台指期與總經來源活著
  4. 雲端看門狗(etf-update Worker):一鍵更新/自動補跑有沒有正常
  5. 排程設定與外部資料來源:Cloudflare cron 星期不能寫數字(1=週日的陷阱);證交所/FRED/Yahoo/期交所抓不抓得到
環境變數:GITHUB_TOKEN(觸發更新、開 Issue)、GITHUB_REPOSITORY;本機測試加 --dry(不觸發、不 commit、不開 Issue)
"""
import json, os, re, sys, time, subprocess, tempfile, datetime as dt, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://yuan780903-cpu.github.io/tw-etf-dividend/"
RAW = "https://raw.githubusercontent.com/yuan780903-cpu/tw-etf-dividend/main/"
ALERT = "https://etf-alert.yuan780903.workers.dev"
UPD = "https://etf-update.yuan780903.workers.dev"
REPO = os.environ.get("GITHUB_REPOSITORY", "yuan780903-cpu/tw-etf-dividend")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
DRY = "--dry" in sys.argv
NOW = dt.datetime.utcnow() + dt.timedelta(hours=8)
TODAY = NOW.date()
ITEMS, FIXES = [], []
UA = {"User-Agent": "Mozilla/5.0 (etf-inspect)"}

def add(g, name, st, msg="", fix=""):
    ITEMS.append({"g": g, "name": name, "st": st, "msg": msg, "fix": fix}); print(f"[{st:5}] {g}｜{name}：{msg} {('→ ' + fix) if fix else ''}", flush=True)

def get(url, timeout=40, data=None, headers=None, raw=False):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read(); return (r.status, b if raw else b.decode("utf-8", "ignore"))

def getj(url, timeout=40):
    try: return json.loads(get(url + ("&" if "?" in url else "?") + f"t={int(time.time())}", timeout)[1])
    except Exception: return None

def gh(path, method="GET", body=None):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "etf-inspect"})
    with urllib.request.urlopen(req, timeout=30) as r:
        t = r.read().decode(); return r.status, (json.loads(t) if t.strip() else None)

def sh(*a, **k): return subprocess.run(a, cwd=ROOT, capture_output=True, text=True, **k)

def ymd(s):
    try: return dt.date.fromisoformat(str(s)[:10])
    except Exception: return None

# ---------------- 1. 網站本體 ----------------
def script_of(html):
    S = [m.group(1) for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)]
    return max(S, key=len) if S else ""

def js_ok(html):
    js = script_of(html)
    if len(js) < 1000: return False, "找不到主程式"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f: f.write(js); p = f.name
    r = subprocess.run(["node", "--check", p], capture_output=True, text=True); os.unlink(p)
    L = r.stderr.strip().splitlines(); e = next((x for x in L if "Error" in x), L[0] if L else "")
    return r.returncode == 0, e[:200] if r.returncode else ""

def rollback_index():
    """把 index.html 還原到最近一個語法正常的版本"""
    log = sh("git", "log", "--format=%H %s", "-n", "40", "--", "index.html").stdout.strip().splitlines()
    for ln in log[1:]:
        h, msg = ln.split(" ", 1)
        old = sh("git", "show", f"{h}:index.html").stdout
        ok, _ = js_ok(old)
        if ok:
            if DRY: return f"（測試模式不還原）可還原到 {h[:8]}"
            open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(old)
            commit(["index.html"], f"🛡️ 每週巡檢自動修復:首頁程式語法錯誤,還原到 {h[:8]}({msg[:40]})")
            return f"已還原到 {h[:8]}（{msg[:30]}）"
    return ""

def check_site():
    g = "網站本體"
    try: st, html = get(SITE + f"?inspect={int(time.time())}", 60)
    except Exception as e: add(g, "首頁", "err", f"打不開：{e}"); return None
    ver = (re.search(r"v20\d\d\.\d\d\.\d\d\.\d+", html) or [None])[0]
    add(g, "首頁", "ok" if st == 200 and len(html) > 300_000 else "err", f"HTTP {st}，{len(html) // 1024} KB，版本 {ver or '找不到'}")
    ok, err = js_ok(html)
    if ok: add(g, "程式語法", "ok", "node --check 通過")
    else:
        head = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
        hok, _ = js_ok(head)
        if hok: add(g, "程式語法", "warn", f"線上版有錯（{err}），但 repo 最新版正常，可能 GitHub Pages 還沒更新完")
        else:
            fx = rollback_index()
            add(g, "程式語法", "err" if not fx or DRY else "fixed", f"語法錯誤：{err}", fx or "找不到可還原的版本，需要人工處理")
            if fx and not DRY: FIXES.append("首頁程式還原：" + fx)
    # 網頁用到的本地檔案＋12 個月 logo
    refs = set(re.findall(r'(?:src|href)="((?!https?:|data:|#|mailto:|javascript:)[^"${}?#]+\.(?:svg|png|js|webmanifest|json|css|ico))"', html))
    refs |= {f"logos/logo-m{m:02d}.svg" for m in range(1, 13)} | {"sw.js", "manifest.webmanifest", "logo.svg"}
    bad = []
    for r in sorted(refs):
        try: s, _ = get(SITE + r, 30, raw=True)
        except urllib.error.HTTPError as e: s = e.code
        except Exception: s = 0
        if s != 200: bad.append(f"{r}（{s}）")
    if not bad: add(g, "網站檔案", "ok", f"{len(refs)} 個檔案都在（含 12 個月 logo、sw.js、manifest）")
    else:
        lg = [b for b in bad if b.startswith("logos/")]
        if lg and not DRY:
            r = sh(sys.executable, "tools/gen_logos.py", "logo.svg", "logos")
            if r.returncode == 0: commit(["logos"], "🛡️ 每週巡檢自動修復:重新產生每月 logo"); FIXES.append("重新產生每月 logo")
        add(g, "網站檔案", "fixed" if lg and not DRY and len(lg) == len(bad) else "err", "讀不到：" + "、".join(bad[:8]), "已重新產生 logo" if lg and not DRY else "")
    check_runtime(g)
    return ver

def check_runtime(g):
    """真的用瀏覽器打開網站(手機與電腦尺寸),收集 JS 錯誤、確認主程式有跑起來"""
    try: from playwright.sync_api import sync_playwright
    except Exception: add(g, "實際開網頁", "warn", "沒有安裝 Playwright，略過（本機測試時正常）"); return
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            for nm, vp in (("電腦", {"width": 1280, "height": 900}), ("手機", {"width": 390, "height": 844})):
                pg = b.new_page(viewport=vp); errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
                pg.goto(SITE + f"?festive=off&inspect={int(time.time())}", wait_until="networkidle", timeout=60000); pg.wait_for_timeout(5000)
                alive = pg.evaluate("typeof LOGO == 'function' && typeof healthUI == 'function' && !!document.querySelector('header')")
                if not alive: add(g, f"實際開網頁（{nm}）", "err", "主程式沒有跑起來" + (f"：{errs[0]}" if errs else ""), "需要人工處理（巡檢會開 Issue）")
                elif errs: add(g, f"實際開網頁（{nm}）", "warn", f"{len(errs)} 個 JS 錯誤：" + "；".join(dict.fromkeys(errs))[:300])
                else: add(g, f"實際開網頁（{nm}）", "ok", "沒有 JS 錯誤，主程式正常啟動")
                pg.close()
            b.close()
    except Exception as e: add(g, "實際開網頁", "warn", f"瀏覽器測試失敗：{str(e)[:160]}")

# ---------------- 2. 資料 ----------------
def dispatch_update():
    if DRY or not TOKEN: return None
    try:
        _, j = gh("/actions/workflows/update.yml/runs?per_page=1"); run = (j or {}).get("workflow_runs", [None])[0]
        if not (run and run["status"] != "completed"):
            gh("/actions/workflows/update.yml/dispatches", "POST", {"ref": "main", "inputs": {"mode": "full"}}); time.sleep(20)
        t0 = time.time()
        while time.time() - t0 < 110 * 60:                      # 最多等 110 分鐘
            _, j = gh("/actions/workflows/update.yml/runs?per_page=1"); run = j["workflow_runs"][0]
            if run["status"] == "completed": return run["conclusion"]
            time.sleep(60)
        return "timeout"
    except Exception as e: print("dispatch 失敗", e); return None

def check_data():
    g = "資料"
    H = getj(RAW + "data/health.json"); upd = ymd((H or {}).get("updated"))
    stale = not upd or (TODAY - upd).days > 3
    errs = [i for i in (H or {}).get("items", []) if i.get("status") == "error"]
    warns = [i for i in (H or {}).get("items", []) if i.get("status") == "warn"]
    if stale or errs:
        why = "每日更新超過 3 天沒跑" if stale else "有資料異常：" + "、".join(i["name"] for i in errs)
        res = dispatch_update()
        H2 = getj(RAW + "data/health.json") if res else None
        e2 = [i for i in (H2 or {}).get("items", []) if i.get("status") == "error"]; u2 = ymd((H2 or {}).get("updated"))
        if res == "success" and not e2 and u2 and (TODAY - u2).days <= 1:
            add(g, "每日資料健康", "fixed", why, "已自動觸發完整更新，重新檢查正常"); FIXES.append("觸發完整更新修好資料：" + why)
        else: add(g, "每日資料健康", "err", why, f"自動更新結果：{res or '沒有觸發（測試模式或沒有權杖）'}" + (f"，仍有問題：{'、'.join(i['name'] for i in e2)}" if e2 else ""))
    else: add(g, "每日資料健康", "warn" if warns else "ok", f"最後檢查 {H.get('updated')}，{len(H.get('items', []))} 份資料" + (f"；注意：{'、'.join(i['name'] + '（' + (i.get('msg') or '') + '）' for i in warns[:4])}" if warns else " 全部正常"))
    # 行事曆:未來 3 週要有美國與台灣的數據日
    C = getj(RAW + "data/calendar.json") or {}
    ev = C.get("ev", []); fut = [e for e in ev if ymd(e.get("d")) and TODAY <= ymd(e["d"]) <= TODAY + dt.timedelta(days=21) and not str(e.get("key", "")).endswith(("HOL", "HALF"))]
    us, tw = sum(1 for e in fut if e.get("c") == "US"), sum(1 for e in fut if e.get("c") == "TW")
    if us >= 3 and tw >= 1: add(g, "經濟行事曆", "ok", f"未來 3 週：美國 {us} 件、台灣 {tw} 件")
    else:
        fixed = False
        if not DRY:
            r = sh(sys.executable, "-u", "scripts/fetch_calendar.py", timeout=600)
            C2 = json.load(open(os.path.join(ROOT, "data/calendar.json"))) if r.returncode == 0 else {}
            us2 = sum(1 for e in C2.get("ev", []) if e.get("c") == "US" and ymd(e.get("d")) and TODAY <= ymd(e["d"]) <= TODAY + dt.timedelta(days=21))
            if us2 >= 3: commit(["data/calendar.json"], "🛡️ 每週巡檢自動修復:重抓經濟行事曆"); fixed = True; FIXES.append(f"重抓行事曆（美國 {us2} 件）")
        add(g, "經濟行事曆", "fixed" if fixed else "err", f"未來 3 週只有美國 {us} 件、台灣 {tw} 件", "已重抓行事曆" if fixed else "重抓後仍不足，可能 FRED 擋了")
    P = getj(RAW + "data/ptt.json") or {}
    m = re.search(r"(\d{4}-\d\d-\d\d)", str(P.get("src", ""))); pd = ymd(m.group(1)) if m else ymd(P.get("updated"))
    add(g, "PTT 討論熱度", "ok" if pd and (TODAY - pd).days <= 3 else "warn", f"最後上傳 {P.get('src') or P.get('updated') or '不明'}",
        "" if pd and (TODAY - pd).days <= 3 else "資料來自 iPhone 捷徑上傳，請確認捷徑自動化還在跑")
    M = getj(RAW + "data/macro.json") or {}; md = ymd(M.get("updated"))
    add(g, "總經資料", "ok" if md and (TODAY - md).days <= 4 else "warn", f"更新 {M.get('updated') or '不明'}")

# ---------------- 3. 雲端推播 Worker ----------------
START = {"am": "2026-11-30", "open": "2026-11-30", "close": "2026-11-30", "inst": "2026-11-25", "no": "2026-11-30", "nc": "2026-11-27", "uso": "2026-11-25", "usc": "2026-11-25"}
NAME = {"am": "晨報", "open": "台股開盤", "close": "台股收盤", "inst": "三大法人", "no": "夜盤開盤", "nc": "夜盤收盤", "uso": "美股開盤", "usc": "美股收盤"}
def check_alert():
    g = "雲端推播"
    C = getj(ALERT + "/coverage?days=8")
    if not C: add(g, "推播 Worker", "err", "連不上 etf-alert（/coverage）", "需要人工：到 Cloudflare 看 Worker 是否正常"); return
    lr = C.get("lastRun"); lt = dt.datetime.fromisoformat(lr.replace("Z", "+00:00")) if lr else None
    age = (dt.datetime.now(dt.timezone.utc) - lt).total_seconds() / 3600 if lt else 999
    add(g, "排程有在跑", "ok" if age < 60 else "err", f"最後執行 {((lt + dt.timedelta(hours=8)).strftime('%m/%d %H:%M') if lt else '不明')}（{age:.0f} 小時前）",
        "" if age < 60 else "需要人工：檢查 Cloudflare Cron（星期要寫 MON-FRI）")
    have = {(x["day"], x["k"]) for x in C.get("items", [])}
    cal = (getj(RAW + "data/calendar.json") or {}).get("ev", [])
    twh = {e["d"] for e in cal if e.get("key") == "TWHOL"}; ush = {e["d"] for e in cal if e.get("key") == "USHOL"}
    miss, dead = [], []
    for i in range(7, 0, -1):
        d = TODAY - dt.timedelta(days=i); ds = d.isoformat()
        if d.weekday() >= 5: continue
        exp = []
        if ds not in twh: exp += ["am", "open", "close", "inst", "no", "nc"]
        if ds not in ush: exp += ["uso", "usc"]
        exp = [k for k in exp if ds >= START[k]]
        lost = [k for k in exp if (ds, k) not in have]
        if lost: miss.append(f"{d.month}/{d.day}（週{'一二三四五'[d.weekday()]}）{'、'.join(NAME[k] for k in lost)}")
        if exp and len(lost) == len(exp): dead.append(f"{d.month}/{d.day}")
    if dead: add(g, "近一週摘要", "err", "整天都沒發：" + "、".join(dead) + "；" + "；".join(miss), "需要人工：多半是排程沒跑（Cloudflare Cron）")
    elif miss: add(g, "近一週摘要", "warn", "漏發：" + "；".join(miss), "個別漏發通常是資料來源當下沒回應，已發的不受影響")
    else: add(g, "近一週摘要", "ok", f"近一週 {len(have)} 則摘要，該發的都有發")
    T = getj(ALERT + "/txnight") or {}
    add(g, "台指期夜盤來源", "ok" if T.get("q") else "err", f"Yahoo 台指期近一 {T['q']['px']:,}" if T.get("q") else f"抓不到：{T.get('err', '')}", "" if T.get("q") else "需要人工：換資料來源")
    try: s, _ = get(ALERT + "/macro", 30); add(g, "總經快訊", "ok" if s == 200 else "err", f"/macro HTTP {s}")
    except Exception as e: add(g, "總經快訊", "err", str(e)[:120])

# ---------------- 4. 雲端看門狗 ----------------
def check_updater():
    g = "雲端看門狗"
    U = getj(UPD + "/status")
    if not U: add(g, "一鍵更新／自動補跑", "err", "連不上 etf-update Worker", "需要人工"); return
    if U.get("status") != "ok": add(g, "一鍵更新／自動補跑", "err", U.get("msg") or str(U)[:120], "需要人工：GH_TOKEN 可能過期，要在 Cloudflare 重設"); return
    run = U.get("run") or {}
    add(g, "一鍵更新／自動補跑", "ok" if run.get("conclusion") in ("success", None) else "warn", f"最近一次雲端更新：{run.get('created', '')[:16].replace('T', ' ')} UTC，{run.get('conclusion') or run.get('status')}")

# ---------------- 5. 排程設定、外部資料來源 ----------------
def check_config_sources():
    g = "排程與來源"
    for f in ("alert/wrangler.toml", "worker/wrangler.toml"):
        try: t = open(os.path.join(ROOT, f), encoding="utf-8").read()
        except Exception: continue
        crons = re.findall(r'"([^"]+)"', (re.search(r"crons\s*=\s*\[([^\]]*)\]", t) or [None, ""])[1])
        bad = [c for c in crons if len(c.split()) == 5 and re.search(r"\d", c.split()[4])]
        add(g, f"Cloudflare 排程 {f.split('/')[0]}", "err" if bad else "ok", ("星期用了數字（Cloudflare 1=週日，會漏掉週五）：" + "、".join(bad)) if bad else "、".join(crons),
            "需要人工：改成 MON-FRI 再部署" if bad else "")
    S = [("證交所", "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=json", None),
         ("FRED（美國數據）", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE&cosd=2026-01-01", None),
         ("Yahoo 報價", "https://query1.finance.yahoo.com/v7/finance/spark?symbols=%5ETWII&range=1d&interval=5m", None),
         ("Yahoo 台指期", "https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.stockList;fields=avgPrice;symbols=WTX%26", None)]
    bad = []
    for nm, u, _ in S:
        try:
            ua = {} if "stlouisfed" in u else None        # FRED 遇到瀏覽器 UA 會卡住
            req = urllib.request.Request(u, headers=ua if ua is not None else UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                if r.status != 200: bad.append(f"{nm}（{r.status}）")
        except Exception as e: bad.append(f"{nm}（{str(e)[:40]}）")
    add(g, "外部資料來源", "warn" if bad else "ok", ("抓不到：" + "、".join(bad)) if bad else "證交所、FRED、Yahoo 報價、Yahoo 台指期都正常")

# ---------------- 輸出 ----------------
def commit(paths, msg):
    if DRY: return
    sh("git", "config", "user.name", "etf-bot"); sh("git", "config", "user.email", "etf-bot@users.noreply.github.com")
    sh("git", "add", *paths)
    if sh("git", "diff", "--cached", "--quiet").returncode == 0: return
    sh("git", "commit", "-m", msg)
    for _ in range(3):
        if sh("git", "pull", "--rebase", "-X", "theirs", "origin", "main").returncode == 0 and sh("git", "push").returncode == 0: return
        time.sleep(10)

def main():
    ver = None
    for f in (check_site, check_data, check_alert, check_updater, check_config_sources):
        try:
            r = f()
            if f is check_site: ver = r
        except Exception as e: add("巡檢程式", f.__name__, "warn", f"這一項巡檢本身出錯：{str(e)[:160]}")
    n = {s: sum(1 for i in ITEMS if i["st"] == s) for s in ("ok", "warn", "err", "fixed")}
    overall = "err" if n["err"] else "warn" if n["warn"] else "ok"
    p = os.path.join(ROOT, "data/inspect.json")
    try: old = json.load(open(p, encoding="utf-8"))
    except Exception: old = {}
    hist = ([{"d": NOW.strftime("%Y-%m-%d %H:%M"), "overall": overall, **n}] + old.get("hist", []))[:12]
    out = {"updated": NOW.strftime("%Y-%m-%d %H:%M"), "version": ver, "overall": overall, "count": n, "items": ITEMS, "fixes": FIXES, "hist": hist,
           "note": "每週日台北 10:00 自動巡檢；能修的自動修（資料重抓、行事曆重抓、logo 重產、首頁程式還原），修不了的會在 GitHub 開 Issue 通知。"}
    if DRY:                                                   # 測試模式:只輸出到 INSPECT_OUT(有設才寫),不 commit
        if os.environ.get("INSPECT_OUT"): json.dump(out, open(os.environ["INSPECT_OUT"], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    commit(["data/inspect.json"], f"🛡️ 每週巡檢 {NOW:%Y-%m-%d}:{ {'ok': '全部正常', 'warn': '有項目要注意', 'err': '有問題'}[overall]}（自動修復 {len(FIXES)} 項）")
    if overall == "err" and TOKEN:
        body = "每週巡檢發現自動修不好的問題：\n\n" + "\n".join(f"- **{i['g']}｜{i['name']}**：{i['msg']}" + (f"（{i['fix']}）" if i["fix"] else "") for i in ITEMS if i["st"] == "err")
        body += "\n\n已自動修復：" + ("、".join(FIXES) if FIXES else "無") + f"\n\n完整報告：{SITE}data/inspect.json"
        try: gh("/issues", "POST", {"title": f"🛡️ 每週巡檢 {NOW:%m/%d} 發現 {n['err']} 個問題", "body": body})
        except Exception as e: print("開 Issue 失敗", e)

if __name__ == "__main__":
    main()
