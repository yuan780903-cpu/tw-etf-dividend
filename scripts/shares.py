"""實際發行股數(證交所/櫃買公司基本資料),修正「非 10 元面額」股票(名稱帶 * 號,如國巨*、寶雅*)
大部分程式用「股本(仟元)×100」換算股數,只對 10 元面額成立;面額 2.5、1、0.5 元或無面額的公司會算錯
每股淨值、殖利率、本益比、市值。這裡提供:
  par_fix(F) -> {代號: 實際股數}  只回傳跟「股本×100」差超過 20% 的公司(其餘照舊)
"""
import json, os, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", "data", "fund", "raw", "shares.json")
UA = {"User-Agent": "Mozilla/5.0"}
_SH = None

def _num(x):
    try: return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError): return None

def issued():
    """{代號: 已發行普通股數};抓不到時沿用快取"""
    global _SH
    if _SH is not None: return _SH
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    out = dict(cache)
    for url, kc, ks in (("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "公司代號", "已發行普通股數或TDR原股發行股數"),
                        ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "SecuritiesCompanyCode", "IssueShares")):
        try:
            rows = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read())
            for r in rows:
                v = _num(r.get(ks))
                if r.get(kc) and v and v > 0: out[r[kc]] = v
        except Exception as e:
            print("  發行股數抓取失敗,沿用快取", url[:60], e)
    if out and out != cache:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True); json.dump(out, open(CACHE, "w"))
    _SH = out; return out

def par_fix(F):
    """F = fundamentals.json 的 companies;回傳需要修正的 {代號: 實際股數}"""
    sh = issued(); fix = {}
    for c, d in F.items():
        cap = (d.get("ttm") or {}).get("cap"); s = sh.get(c)
        if cap and s and abs(cap * 100 / s - 1) > 0.2: fix[c] = s
    return fix

if __name__ == "__main__":
    F = json.load(open(os.path.join(HERE, "..", "data", "fund", "fundamentals.json")))["companies"]
    fx = par_fix(F)
    print(len(fx), "家非 10 元面額:", ", ".join(f"{c}{F[c]['name']}(×{F[c]['ttm']['cap'] * 100 / s:.2f})" for c, s in fx.items()))
