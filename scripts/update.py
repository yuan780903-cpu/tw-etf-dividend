"""每日增量更新(GitHub Actions 每天跑,也可手動一鍵觸發)
1. 重抓ETF清單 -> 新上市的ETF自動補齊5年歷史
2. 證交所+櫃買「全市場當日收盤」各1次請求 -> 所有ETF補今天股價(不吃FinMind額度)
3. 有缺漏天數 / 新分割的ETF -> 用FinMind補
4. 配息:優先更新「快除息、剛除息、有預告」的ETF,其餘輪流更新
5. 持股/規模:每天輪流更新最舊的一批(約一週全部輪完)
6. 重建 summary.json
FinMind 免token每小時300次;設環境變數 FINMIND_TOKEN 可提高到600次。
"""
import time, json, os, sys, subprocess, datetime as dt, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
os.environ.setdefault("FINMIND_NO_WAIT", "1")      # 雲端不要睡等額度,用完就收工,下次再補
import fetch_history as fh

DATA = fh.DATA
TODAY = dt.date.today()
BUDGET = int(os.environ.get("FINMIND_BUDGET", "500" if fh.TOKEN else "250"))   # 本次最多打幾次 FinMind
if os.environ.get("MODE", "full") == "quick": BUDGET = 0      # 一鍵快速更新:不打 FinMind(ETF 補缺/配息留給排程完整更新)
used = 0
UA = {"User-Agent": "Mozilla/5.0"}

def spend(n=1):
    global used; used += n
    return used <= BUDGET

def load(p, default=None):
    try: return json.load(open(p))
    except Exception: return default

def roc(d):  # 1151104 -> 2026-11-04
    return f"{int(d[:3]) + 1911}-{d[3:5]}-{d[5:7]}"

def num(s):
    try: return float(str(s).replace(",", "").strip())
    except ValueError: return None

def get_json(url, timeout, tries=3):
    for i in range(tries):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read())
        except Exception as e:
            if i == tries - 1: raise
            print(f"  重試 {i+1}: {e}")

STAMP_P = os.path.join(DATA, "div_stamps.json")      # 配息上次更新日(不能用檔案 mtime,雲端 checkout 會重設)
STAMPS = load(STAMP_P, {}) or {}

def stamp(sid):
    STAMPS[sid] = TODAY.isoformat(); fh.save(STAMP_P, STAMPS)

def bulk_quotes():
    """上市+上櫃當日收盤(全市場一次抓)"""
    q = {}
    try:
        tw = get_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", 90)
        for x in tw:
            c = num(x["ClosingPrice"])
            if c: q[x["Code"]] = [roc(x["Date"]), num(x["OpeningPrice"]), num(x["HighestPrice"]), num(x["LowestPrice"]), c, round((num(x["TradeVolume"]) or 0) / 1000)]
    except Exception as e: print("證交所當日行情失敗:", e)
    try:
        tp = get_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes", 180)
        for x in tp:
            c = num(x["Close"])
            if c: q[x["SecuritiesCompanyCode"]] = [roc(x["Date"]), num(x["Open"]), num(x["High"]), num(x["Low"]), c, round((num(x["TradingShares"]) or 0) / 1000)]
    except Exception as e: print("櫃買當日行情失敗:", e)
    print("當日行情", len(q), "檔")
    return q

def fill_taiex():
    """加權指數:FinMind 晚上才有當天資料 → 用證交所官方每日指數(MI_5MINS_HIST 開高低收＋FMTQIK 成交股數)補上缺的交易日"""
    import net  # noqa: F401  證交所 cookie/307
    p = os.path.join(DATA, "taiex.json"); rows = load(p, []) or []; last = rows[-1][0] if rows else "0"
    n = lambda x: float(str(x).replace(",", ""))
    add = {}
    m0 = TODAY.replace(day=1)
    for m in sorted({m0, (m0 - dt.timedelta(days=1)).replace(day=1)}):
        try:
            o = json.loads(urllib.request.urlopen(urllib.request.Request(f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={m:%Y%m}01&response=json", headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read())
            v = json.loads(urllib.request.urlopen(urllib.request.Request(f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={m:%Y%m}01&response=json", headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read())
            vol = {r[0]: round(n(r[1]) / 1000) for r in v.get("data", [])}
            for r in o.get("data", []):
                y, mm, dd = r[0].split("/"); d = f"{int(y) + 1911}-{mm}-{dd}"
                if d > last: add[d] = [d, n(r[1]), n(r[2]), n(r[3]), n(r[4]), vol.get(r[0])]
        except Exception as e: print("  證交所指數補資料失敗:", e)
        time.sleep(1)
    if add:
        rows += [add[d] for d in sorted(add)]; fh.save(p, rows); print("  加權指數用證交所補上:", ", ".join(sorted(add)))

QUICK = os.environ.get("MODE", "full") == "quick"   # 一鍵更新:只重算當天會變的大盤/法人/籌碼(約 10～15 分鐘)

STEPS = []                     # 每一步的結果,寫進 data/run_log.json 給資料健康面板看
LONG = {"fetch_breadth.py": 2700, "fetch_fundamentals.py": 2700, "fetch_holdings.py": 1800, "fetch_market.py": 1500, "fetch_chips.py": 1500, "fetch_risk.py": 1200, "fetch_divs.py": 1200}
def step(script, *args, quiet=False):
    """執行一個腳本:有時間上限、失敗或逾時都不中斷後面的步驟(避免整次更新只做一半)"""
    t0 = time.time(); rc = -1; note = ""
    try:
        rc = subprocess.run([sys.executable, os.path.join(HERE, script), *args], timeout=LONG.get(script, 900),
                            stdout=subprocess.DEVNULL if quiet else None).returncode
        if rc: note = f"結束代碼 {rc}"
    except subprocess.TimeoutExpired: note = f"超過 {LONG.get(script, 900) // 60} 分鐘，已中止"; print("  逾時:", script)
    except Exception as e: note = str(e)[:120]
    STEPS.append(dict(s=script, ok=rc == 0, sec=round(time.time() - t0), note=note))
    try: fh.save(os.path.join(DATA, "run_log.json"), dict(at=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), steps=STEPS))
    except Exception: pass
    return rc

def main():
    global used
    if os.environ.get("MODE") == "ptt":     # iPhone 上傳完 PTT 後:只重算 PTT 熱度(約 1 分鐘)
        subprocess.run([sys.executable, os.path.join(HERE, "fetch_ptt.py")], timeout=300); return
    new_ids = []
    try:                       # ETF 價格/配息階段:任何意外都不能讓後面的大盤、選股、驗證步驟停擺
        # 1. ETF 清單(新上市)
        old_ids = {e["id"] for e in load(os.path.join(DATA, "etf_master.json"), [])}
        rc = step("build_master.py", quiet=True) if not QUICK else 0; spend()
        if rc: print("ETF清單更新失敗,沿用舊清單")
        master = load(os.path.join(DATA, "etf_master.json"))
        new_ids = [e["id"] for e in master if e["id"] not in old_ids]
        print("新上市ETF:", new_ids or "無")

        # 2. 分割 + 大盤
        old_splits = load(os.path.join(DATA, "splits.json"), {})
        try:
            if QUICK: raise RuntimeError("快速模式沿用分割資料")
            fh.load_splits(); spend()
        except Exception as ex: print("分割資料:", ex); fh.SPLITS.update({k: [tuple(x) for x in v] for k, v in old_splits.items()})
        new_split = [k for k in fh.SPLITS if fh.SPLITS[k] != [tuple(x) for x in old_splits.get(k, [])] and k in {e["id"] for e in master}]
        if not QUICK:
            try: fh.save(os.path.join(DATA, "taiex.json"), fh.fetch_prices("TAIEX")); spend()
            except Exception as ex: print("大盤更新失敗:", ex)
        fill_taiex()
        tx_dates = [r[0] for r in load(os.path.join(DATA, "taiex.json"))]
        last_trade = tx_dates[-1]; prev_trade = tx_dates[-2]

        # 3. 股價:當日行情直接接上;有缺漏/新上市/新分割 -> FinMind 重抓
        q = bulk_quotes()
        need_full = set(new_ids) | set(new_split)
        appended = 0
        for e in master:
            sid = e["id"]; pp = os.path.join(DATA, "prices", sid + ".json")
            rows = load(pp)
            if rows is None: need_full.add(sid); continue
            if sid in need_full: continue
            last = rows[-1][0] if rows else ""
            bar = q.get(sid)
            if bar and bar[0] > last:
                if last and last < prev_trade and bar[0] == last_trade:
                    need_full.add(sid); continue        # 中間漏了交易日 -> 用FinMind整段重抓比較保險
                rows.append(bar); fh.save(pp, rows); appended += 1
        print(f"當日股價接上 {appended} 檔;需重抓 {len(need_full)} 檔")
        for sid in sorted(need_full):
            if not spend(2): print("FinMind 本次預算用完,其餘下次再補"); break
            try:
                fh.save(os.path.join(DATA, "prices", sid + ".json"), fh.fetch_prices(sid))
                fh.save(os.path.join(DATA, "dividends", sid + ".json"), fh.fetch_divs(sid)); stamp(sid)
            except fh.QuotaError: print("FinMind 額度用完,其餘下次再補"); used = BUDGET; break

        # 4. 配息:依急迫程度排序後,用剩下的額度更新
        summ = {e["id"]: e for e in (load(os.path.join(DATA, "summary.json"), {}) or {}).get("etfs", [])}
        upcoming = {u["id"] for u in load(os.path.join(DATA, "upcoming.json"), []) or []}
        def urgency(e):
            sid = e["id"]; s = summ.get(sid, {}); dp = os.path.join(DATA, "dividends", sid + ".json")
            age = (TODAY - dt.date.fromisoformat(STAMPS[sid])).days if sid in STAMPS and os.path.exists(dp) else 999
            last_ex = (s.get("lastDiv") or {}).get("ex", "")
            recent = last_ex and (TODAY - dt.date.fromisoformat(last_ex)).days < 45          # 剛除息:等發放日/金額確認
            soon = TODAY.month in (s.get("exMonths") or []) or (TODAY.month % 12 + 1) in (s.get("exMonths") or [])
            return (0 if sid in upcoming else 1 if recent else 2 if soon else 3, -age)
        queue = sorted([e for e in master if e["id"] not in need_full and summ.get(e["id"], {}).get("perYear", 1)], key=urgency)
        n = 0
        for e in queue:
            if urgency(e)[1] == 0: continue        # 今天已更新
            if not spend(): break
            try: fh.save(os.path.join(DATA, "dividends", e["id"] + ".json"), fh.fetch_divs(e["id"])); stamp(e["id"]); n += 1
            except fh.QuotaError: print("FinMind 額度用完"); break
        print("配息更新", n, "檔")
    except Exception as ex:
        import traceback; traceback.print_exc(); STEPS.append(dict(s="ETF 價格/配息", ok=False, sec=0, note=str(ex)[:120]))

    if QUICK:                          # 一鍵快速更新(約 10～15 分鐘):只重算當天會變的大盤、法人、籌碼、風險、期權
        print("== 快速模式 ==")
        for x in (("build_summary.py",), ("fetch_inst.py",), ("fetch_market.py",), ("build_futures.py",), ("build_macro_map.py",), ("fetch_breadth.py", "--keep", "300", "--max", "300"), ("build_tech.py",),
                  ("build_market_analysis.py",), ("fetch_news.py",), ("fetch_chips.py",), ("build_board.py",), ("fetch_risk.py",), ("fetch_options.py",),
                  ("build_concepts.py",), ("build_smart.py",), ("fetch_calendar.py",), ("fetch_ptt.py",)):
            step(*x)
        step("validate.py"); print("快速模式完成"); return
    # 5. 持股/規模輪流更新
    step("fetch_holdings.py", "--oldest", os.environ.get("HOLDINGS_PER_RUN", "70"), *(["--ids", ",".join(new_ids)] if new_ids else []))

    # 6. 總表
    step("build_summary.py")

    # 7. 大盤儀表板(融資/維持率/追繳/法人/期貨/VIX/全球指數),失敗不影響 ETF 資料
    step("fetch_inst.py")              # 三大法人買賣超(上市＋上櫃),大盤歷史/總表/總經/行事曆共用(先抓,當天就有)
    step("fetch_market.py")
    step("build_futures.py")           # 外資台指期空單:合理區間、空單成本、避險比例
    step("fetch_breadth.py", "--keep", "300", "--max", "300")   # 市場廣度(恐慌度用)
    step("scan_patterns.py")   # 線型選股(全市場掃描)
    step("build_tech.py")      # 日線技術面買點訊號(大師選股/定存股搭配用)
    step("build_fill.py")      # 個股填息分析(用近 300 日收盤)
    step("build_market_analysis.py")
    step("fetch_news.py")        # 盤勢快訊(標題)
    step("fetch_macro.py")       # 美國總經(FRED)
    step("build_macro_map.py")   # 總經現況 vs 基準 → 對應的大盤指數
    step("fetch_profiles.py", "--max", "150")   # 公司檔案輪替更新

    # 8. 巴菲特選股(財報一季更新一次、已抓過的期別會跳過;股價/月營收每天更新)
    ff = [sys.executable, os.path.join(HERE, "fetch_fundamentals.py")] + (["--refresh-latest"] if TODAY.weekday() == 0 else [])   # 最新一季每週一重抓(補晚交財報的公司)
    if step("fetch_fundamentals.py", *ff[2:]) == 0:
        step("build_value_picks.py")
        step("build_experts.py")      # 專家選股(9 位大師條件)
    step("fetch_divs.py")               # 個股股利排行+除權息行事曆
    step("fetch_ratings.py")            # 券商評等/法人共識目標價
    step("fetch_chips.py")              # 三大法人個股、集保大戶、熱力圖
    step("fetch_events.py")             # 法說會、內部人持股轉讓
    step("build_stock_pages.py")        # 量化評分、個股分析頁、月營收排行、搜尋名單
    step("build_board.py")              # 大盤總表(含台指期夜盤)
    step("fetch_risk.py")              # 風險雷達:處置/注意股、借券、外資持股、當沖比
    step("fetch_options.py")           # 期權籌碼:P/C、最大未平倉、外資選擇權、ADR 溢價
    step("build_concepts.py")          # 族群／概念股輪動
    step("build_smart.py")             # 綜合評分 1～10、大戶吸籌
    step("build_backtest.py")          # 大師選股歷年回測
    step("fetch_calendar.py")          # 經濟行事曆(美國 FRED/Fed、台灣慣例日期、除息、法說會)
    step("fetch_ptt.py")               # PTT 股版熱度(只抓標題)
    step("validate.py")               # 資料健康檢查:筆數、範圍、交叉比對;抓壞自動還原上一版 → health.json
    print(f"完成。FinMind 用了 {used}/{BUDGET} 次")

if __name__ == "__main__":
    main()
