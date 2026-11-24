"""資料健康檢查(每次雲端更新最後執行)-> data/health.json
1. 每個資料檔:能不能讀、筆數夠不夠、數值在合理範圍、日期是否新鮮
2. 防止「抓壞了蓋掉好資料」:筆數比上一版(git HEAD)少一半以上 → 自動還原上一版並標記
3. 交叉比對:總表加權指數＝歷史最後一筆、總表外資＝三大法人資料、各檔日期一致性
網站「🩺 資料健康」面板會讀 health.json;任何一項 error 會在網頁頂端提醒
"""
import json, os, sys, subprocess, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA; ROOT = os.path.dirname(DATA)
NOW = dt.datetime.utcnow() + dt.timedelta(hours=8)

def L(n):
    p = os.path.join(DATA, n)
    try: return json.load(open(p))
    except Exception: return None
def git_old(n):
    try: return json.loads(subprocess.run(["git", "show", f"HEAD:data/{n}"], cwd=ROOT, capture_output=True, text=True, timeout=60).stdout)
    except Exception: return None

def expected_day():
    """最近一個應該有收盤資料的交易日(週一～五;下午 3 點後算今天)"""
    d = NOW.date() if NOW.hour >= 15 else NOW.date() - dt.timedelta(days=1)
    while d.weekday() >= 5: d -= dt.timedelta(days=1)
    try:                                                   # 扣掉證交所公告的休市日
        hol = {e["d"] for e in (L("calendar.json") or {}).get("ev", []) if e.get("key") == "TWHOL"}
        while d.isoformat() in hol or d.weekday() >= 5: d -= dt.timedelta(days=1)
    except Exception: pass
    return d
EXP = expected_day()
def ymd(x):
    if not x: return None
    x = str(x).replace("/", "-")[:10]
    if len(x) == 8 and x.isdigit(): x = f"{x[:4]}-{x[4:6]}-{x[6:]}"
    try: return dt.date.fromisoformat(x)
    except Exception: return None
def trading_gap(d):
    if not d: return 99
    n, x = 0, d
    while x < EXP:
        x += dt.timedelta(days=1)
        if x.weekday() < 5: n += 1
    return n

# 名稱, 檔案, 取筆數, 取日期, 允許落後幾個交易日, 其他檢查
SPEC = [
  ("大盤歷史", "market.json", lambda j: len(j["rows"]), lambda j: j["rows"][-1][0], 1, lambda j: [f"{r[0]} 加權單日 {((r[1] / p[1]) - 1) * 100:.1f}%" for p, r in zip(j["rows"][-30:-1], j["rows"][-29:]) if abs(r[1] / p[1] - 1) > .11]),
  ("大盤總表", "board.json", lambda j: 1, lambda j: j["taiex"]["d"], 1, None),
  ("三大法人", "inst.json", lambda j: len((j.get("twse") or {}).get("fiH") or []), lambda j: j["twse"]["d"], 1, lambda j: [f"外資單日 {j['twse']['fi']} 億異常"] if abs(j["twse"]["fi"]) > 5000 else []),
  ("ETF 總表", "summary.json", lambda j: len(j["etfs"]), lambda j: max(e.get("date") or "" for e in j["etfs"]), 1, lambda j: [f"{e['id']} 價格異常" for e in j["etfs"] if not e.get("price") or e["price"] <= 0][:5]),
  ("量化評分", "scores.json", lambda j: len(j["stocks"]), lambda j: j["updated"], 2, None),
  ("大師選股", "experts.json", lambda j: len(j["stocks"]), lambda j: j["updated"], 2, None),
  ("定存股", "dingcun.json", lambda j: len(j["stocks"]), lambda j: j["updated"], 2, None),
  ("日線技術", "tech.json", lambda j: len(j["s"]), lambda j: j["d"], 1, None),
  ("風險股", "risk.json", lambda j: len(j["s"]), lambda j: j["d"], 1, lambda j: ["風險旗標過多，可能資料異常"] if len(j["flags"]) > 600 else []),
  ("外資期貨空單", "futures.json", lambda j: len(j["H"]), lambda j: j["d"], 1, lambda j: [f"外資淨未平倉 {j['now']['fi']} 口異常"] if abs(j["now"]["fi"]) > 300000 else []),
  ("總經對應指數", "macro_map.json", lambda j: len(j["rows"]), lambda j: j["updated"], 3, None),
  ("三大法人歷史", "inst_hist.json", lambda j: len(j["twse"]["rows"]), lambda j: j["twse"]["rows"][-1][0], 1, None),
  ("期權籌碼", "options.json", lambda j: len(j["pcr"]), lambda j: j["pcr"][-1][0], 1, None),
  ("熱力圖", "heatmap.json", lambda j: len(j["items"]), lambda j: j["date"], 1, None),
  ("籌碼", "chips.json", lambda j: len(j["stocks"]), lambda j: j["days"][-1], 2, None),
  ("月營收", "rev_rank.json", lambda j: len(j["stocks"]), lambda j: j["updated"], 3, None),
  ("總經", "macro.json", lambda j: len(j["s"]), lambda j: j["updated"], 3, None),
  ("恐慌度分析", "market_analysis.json", lambda j: len(j.get("cards") or []), lambda j: j["updated"], 1, None),
  ("族群輪動", "concepts.json", lambda j: len(j["c"]), lambda j: j["d"], 1, None),
  ("綜合評分", "smart.json", lambda j: len(j["s"]), lambda j: j["updated"], 2, None),
  ("行事曆", "calendar.json", lambda j: len(j["ev"]), lambda j: j["updated"], 3, None),
  ("PTT 熱度", "ptt.json", lambda j: j["n"], lambda j: j["updated"], 3, None),
  ("新聞", "news.json", lambda j: sum(len(v) for v in j["feeds"].values()), lambda j: j["updated"], 2, None),
  ("大師回測", "backtest.json", lambda j: len(j["years"]), lambda j: j["updated"], 10, None),
  ("填息", "fill.json", lambda j: len(j["s"]), lambda j: j["updated"], 3, None),
  ("股利", "stock_div.json", lambda j: len(j["stocks"]), lambda j: j["updated"], 3, None),
  ("法說會", "events.json", lambda j: len(j["conf"]), lambda j: j["updated"], 3, None),
]
MIN = {"market.json": 1000, "summary.json": 300, "scores.json": 1500, "experts.json": 1500, "dingcun.json": 300, "tech.json": 1500, "risk.json": 1500,
       "options.json": 5, "heatmap.json": 1500, "chips.json": 1500, "rev_rank.json": 1500, "macro.json": 15, "concepts.json": 10, "smart.json": 1500,
       "calendar.json": 10, "ptt.json": 50, "news.json": 20, "backtest.json": 3, "fill.json": 300, "stock_div.json": 1500, "events.json": 50, "inst.json": 10, "futures.json": 100, "macro_map.json": 15, "inst_hist.json": 200}

def main():
    items, restored = [], []
    for name, f, cnt, day, lag, extra in SPEC:
        it = dict(k=f, name=name, status="ok", msg="")
        j = L(f)
        if j is None:
            it.update(status="error", msg="檔案不存在或無法讀取"); items.append(it); continue
        try: n = cnt(j)
        except Exception as e: n = 0; it.update(status="error", msg=f"格式錯誤：{e}")
        old = git_old(f)
        try: on = cnt(old) if old else 0
        except Exception: on = 0
        if on >= 20 and n < on * .5:                       # 筆數掉一半以上:抓壞了 → 還原上一版
            subprocess.run(["git", "checkout", "HEAD", "--", f"data/{f}"], cwd=ROOT, capture_output=True)
            bad_n = n; restored.append(f); j = L(f); n = cnt(j)
            it.update(status="warn", msg=f"新抓的資料只有 {bad_n} 筆（上一版 {on} 筆），判定抓取失敗，已自動還原上一版")
        it["n"] = n
        if n < MIN.get(f, 1) and it["status"] == "ok": it.update(status="warn", msg=f"筆數偏少（{n}，應至少 {MIN.get(f)}）")
        try: d = ymd(day(j))
        except Exception: d = None
        it["d"] = d.isoformat() if d else None
        g = trading_gap(d)
        if d and g > lag and it["status"] == "ok": it.update(status="warn" if g <= lag + 2 else "error", msg=f"資料日期 {d.isoformat()}，落後 {g} 個交易日")
        if extra:
            try:
                bad = extra(j)
                if bad and it["status"] == "ok": it.update(status="warn", msg="、".join(bad[:3]))
            except Exception: pass
        items.append(it)
    # 交叉比對
    cross = []
    M, B, I = L("market.json"), L("board.json"), L("inst.json")
    try:
        last = dict(zip(M["cols"], M["rows"][-1]))
        if B["taiex"]["d"] == last["d"] and abs(B["taiex"]["v"] - last["tx"]) > .01: cross.append(("error", f"總表加權 {B['taiex']['v']} ≠ 歷史最後一筆 {last['tx']}"))
        if I and I.get("twse") and B.get("foreign", {}).get("d") == I["twse"]["d"] and abs(B["foreign"]["v"] - I["twse"]["fi"]) > .01: cross.append(("error", "總表外資與三大法人資料不一致"))
        ds = {k: ymd(v) for k, v in (("加權", B["taiex"].get("d")), ("櫃買", (B.get("otc") or {}).get("d")), ("外資", (B.get("foreign") or {}).get("d"))) if v}
        if len(set(ds.values())) > 1: cross.append(("warn", "總表各格資料日期不同：" + "、".join(f"{k} {v.month}/{v.day}" for k, v in ds.items())))
        if I and I.get("twse") and last["d"].replace("-", "") == I["twse"]["d"] and abs(last["fi"] - I["twse"]["fi"]) > .05: cross.append(("error", f"三大法人外資 {I['twse']['fi']} 與大盤歷史 {last['fi']} 不一致"))
        if I and I.get("twse") and last["d"].replace("-", "") == I["twse"]["d"] and last.get("it") is not None and abs(last["it"] - I["twse"]["it"]) > .05: cross.append(("warn", f"三大法人投信 {I['twse']['it']} 與大盤歷史 {last['it']} 不一致"))
    except Exception as e: cross.append(("warn", f"交叉比對無法完成：{e}"))
    RL = L("run_log.json") or {}                          # 這次更新每一步的執行結果
    fails = [x for x in RL.get("steps", []) if not x.get("ok")]
    for x in fails: cross.append(("warn", f"更新步驟 {x['s']} 沒有完成（{x.get('note') or '失敗'}），沿用上一版資料"))
    st = [i["status"] for i in items] + [c[0] for c in cross]
    overall = "error" if "error" in st else "warn" if "warn" in st else "ok"
    fh.save(os.path.join(DATA, "health.json"), dict(updated=NOW.strftime("%Y-%m-%d %H:%M"), expected=EXP.isoformat(), overall=overall, items=items,
            cross=[dict(status=a, msg=b) for a, b in cross], restored=restored, run=dict(at=RL.get("at"), n=len(RL.get("steps", [])), fail=len(fails), sec=sum(x.get("sec", 0) for x in RL.get("steps", []))),
            note="每次雲端更新最後自動檢查；筆數掉一半以上會自動還原上一版，避免網站出現抓一半的資料"))
    bad = [i for i in items if i["status"] != "ok"]
    print(f"health.json:{overall};{len(items)} 項,{len(bad)} 項需注意,還原 {restored};交叉比對 {[c[1] for c in cross]}")
    for i in bad: print("  ", i["status"], i["name"], i["msg"])

if __name__ == "__main__":
    main()
