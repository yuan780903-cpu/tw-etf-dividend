"""全市場當日收盤行情(上市＋上櫃),給 update.py、fetch_chips.py、fetch_fundamentals.py、build_futures.py 共用。
證交所/櫃買的 OpenAPI 通常要到晚上(甚至隔天早上)才更新到當天,下午按「一鍵更新」會拿到前一天的價格。
所以先抓官網的當日行情(收盤後約 14:30 就有),抓不到(還沒收盤、休市、網站故障)才退回 OpenAPI。
回傳格式和 OpenAPI 一模一樣,原本解析 OpenAPI 的程式不用改。
"""
import json, re, time, datetime as dt, urllib.request
try:
    import net  # noqa: F401  證交所 cookie/307
except Exception:
    pass

_CACHE = {}


def _get(url, timeout=90):
    for i in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r: return r.read()
        except Exception as e:
            if i == 2: print("  行情抓取失敗:", url.split("?")[0][-60:], e)
            else: time.sleep(4 + i * 4)
    return None


def _json(url, timeout=90):
    b = _get(url, timeout)
    try: return json.loads(b) if b else None
    except Exception: return None


def _clean(s):
    s = re.sub(r"<[^>]+>", "", str(s if s is not None else "")).replace(",", "").strip()
    return "" if s in ("--", "---", "----", "X", "除權", "除息", "除權息") else s


def _today():
    return (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()


def _roc(ymd):           # "20261125" -> "1151125"(和 OpenAPI 的 Date 欄位一樣)
    return f"{int(ymd[:4]) - 1911}{ymd[4:8]}"


def twse_all():
    """上市:OpenAPI exchangeReport/STOCK_DAY_ALL 格式"""
    if "twse" in _CACHE: return _CACHE["twse"]
    out, d = [], _today()
    j = _json(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d:%Y%m%d}&type=ALLBUT0999&response=json")
    try:
        if j and j.get("stat") == "OK":
            t = next(t for t in j.get("tables", []) if len(t.get("data") or []) > 500 and "證券代號" in (t.get("fields") or []))
            F = {k: i for i, k in enumerate(t["fields"])}
            day = _roc(j["date"])
            for r in t["data"]:
                sign = "-" if "-" in _clean(r[F["漲跌(+/-)"]]) else ""
                ch = _clean(r[F["漲跌價差"]])
                out.append({"Date": day, "Code": _clean(r[F["證券代號"]]), "Name": _clean(r[F["證券名稱"]]),
                            "TradeVolume": _clean(r[F["成交股數"]]), "TradeValue": _clean(r[F["成交金額"]]),
                            "OpeningPrice": _clean(r[F["開盤價"]]), "HighestPrice": _clean(r[F["最高價"]]),
                            "LowestPrice": _clean(r[F["最低價"]]), "ClosingPrice": _clean(r[F["收盤價"]]),
                            "Change": (sign + ch) if ch else "0", "Transaction": _clean(r[F["成交筆數"]])})
    except Exception as e:
        print("  證交所官網行情解析失敗:", e); out = []
    src = "官網"
    if len(out) < 500:
        out = _json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL") or []; src = "OpenAPI"
    if out: print(f"  上市行情 {len(out)} 檔,日期 {out[0].get('Date')}({src})")
    _CACHE["twse"] = out
    return out


def tpex_all():
    """上櫃:OpenAPI tpex_mainboard_daily_close_quotes 格式"""
    if "tpex" in _CACHE: return _CACHE["tpex"]
    out, d = [], _today()
    j = _json(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={d:%Y}%2F{d:%m}%2F{d:%d}&id=&response=json", 180)
    try:
        if j and j.get("stat", "").lower() == "ok" and j.get("tables"):
            t = j["tables"][0]; F = {k.replace(" ", ""): i for i, k in enumerate(t.get("fields") or [])}
            day = _roc(str(j.get("date") or f"{d:%Y%m%d}"))
            for r in t.get("data") or []:
                ch = _clean(r[F["漲跌"]]).replace("+", "")
                try: float(ch)
                except ValueError: ch = ""
                out.append({"Date": day, "SecuritiesCompanyCode": _clean(r[F["代號"]]), "CompanyName": _clean(r[F["名稱"]]),
                            "Close": _clean(r[F["收盤"]]), "Change": ch, "Open": _clean(r[F["開盤"]]), "High": _clean(r[F["最高"]]),
                            "Low": _clean(r[F["最低"]]), "Average": _clean(r[F["均價"]]), "TradingShares": _clean(r[F["成交股數"]]),
                            "TransactionAmount": _clean(r[F["成交金額(元)"]]), "TransactionNumber": _clean(r[F["成交筆數"]])})
    except Exception as e:
        print("  櫃買官網行情解析失敗:", e); out = []
    src = "官網"
    if len(out) < 500:
        out = _json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes", 180) or []; src = "OpenAPI"
    if out: print(f"  上櫃行情 {len(out)} 檔,日期 {out[0].get('Date')}({src})")
    _CACHE["tpex"] = out
    return out


if __name__ == "__main__":
    a, b = twse_all(), tpex_all()
    print(next((x for x in a if x["Code"] == "0050"), None))
    print(next((x for x in b if x["SecuritiesCompanyCode"] == "006201"), None))
