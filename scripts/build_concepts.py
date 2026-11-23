"""族群／概念股輪動 -> data/concepts.json
概念股名單依公開報導整理(會自動剔除已下市或代號不存在的股票);每天計算:
  今日漲跌(市值加權)、5 日／20 日漲跌(等權)、外資＋投信 5 日買賣超(億元)、上漲家數、領漲股、族群內線型訊號分布
資料:heatmap.json(今日收盤、市值)、tech.json(5/20 日)、chips.json(法人 5 日張數)
"""
import json, os, sys, datetime as dt, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
DATA = fh.DATA
L = lambda n, d=None: json.load(open(os.path.join(DATA, n))) if os.path.exists(os.path.join(DATA, n)) else d

C = [  # [名稱, 圖示, 白話說明, 代號...]
  ["AI 伺服器", "🖥️", "幫 AI 公司組裝超級電腦的代工廠", "2382 3231 6669 2356 2317 3706 2376 2357 4938 2324"],
  ["CoWoS 先進封裝", "🧩", "把多顆 AI 晶片黏在一起的高級封裝技術與設備", "2330 3711 3131 6187 3583 6640 2467 1560 3680 6510"],
  ["AI 晶片設計（ASIC／IP）", "🧠", "幫大廠客製 AI 晶片、賣晶片設計藍圖的公司", "3443 3661 2454 3035 6643 5274 3529 6531"],
  ["散熱", "❄️", "AI 晶片很燙，幫它降溫的風扇、水冷公司", "3017 3324 2421 3653 6230 8996 3338"],
  ["矽光子／光通訊", "💡", "用光代替電來傳資料，更快更省電", "3363 4979 3081 4977 3450 6442 3105 2455 4908"],
  ["PCB／銅箔基板", "🟩", "電子產品的「地基」電路板與材料", "2383 6274 6213 2368 3037 8046 3189 4958 2313"],
  ["記憶體", "💾", "電腦和手機用來記東西的晶片", "2408 2344 2337 3260 8299 4967 3006"],
  ["重電／電網", "⚡", "變壓器、配電盤，AI 機房和綠電都需要", "1503 1519 1513 1514 1504 1609"],
  ["機器人／自動化", "🤖", "工廠自動化的手臂、零件與視覺", "2049 1590 4583 2359 8374 2365"],
  ["網通／低軌衛星", "🛰️", "交換器、Wi-Fi、衛星通訊設備", "2345 6285 3380 5388 4906 3596 2314 3491"],
  ["航運", "🚢", "貨櫃與散裝船運、航空", "2603 2609 2615 2618 2610 2606 2637"],
  ["金融", "🏦", "銀行、保險、證券的金控公司", "2881 2882 2891 2886 2884 2885 2892 5880 2880 2887"],
  ["生技醫療", "🧬", "新藥、學名藥、醫材公司", "6446 1795 4743 6472 4147 1760"],
  ["汽車／電動車零件", "🚗", "汽車與電動車的零組件", "2201 2207 1536 2231 3665 2308"],
  ["塑化／鋼鐵（傳產）", "🏭", "台塑集團、中鋼等景氣循環的原料股", "2002 1301 1303 1326 6505 2027"],
  ["半導體設備／耗材", "🔧", "晶圓廠擴廠時要買的設備和耗材", "3131 3583 6187 2467 5536 6196 3680"],
]

def main():
    hm = {x[0]: x for x in (L("heatmap.json", {}) or {}).get("items", [])}
    T = (L("tech.json", {}) or {}).get("s", {}); K = (L("chips.json", {}) or {}).get("stocks", {})
    names = {r[0]: r[1] for r in (L("names.json", []) or [])}
    out = []
    for n, ic, why, codes in C:
        m = [c for c in codes.split() if c in hm]
        if len(m) < 3: continue
        cap = sum(hm[c][3] or 0 for c in m)
        chg = sum((hm[c][4] or 0) * (hm[c][3] or 0) for c in m) / cap if cap else None
        r5 = [T[c][5] for c in m if c in T and T[c][5] is not None]; r20 = [T[c][6] for c in m if c in T and T[c][6] is not None]
        inst = sum(((K.get(c) or {}).get("f5", 0) + (K.get(c) or {}).get("t5", 0)) * 1000 * (hm[c][5] or 0) for c in m) / 1e8
        sig = {}
        for c in m:
            if c in T: sig[T[c][1]] = sig.get(T[c][1], 0) + 1
        lead = sorted(m, key=lambda c: -(hm[c][4] or 0))
        out.append(dict(n=n, ic=ic, why=why, m=[[c, names.get(c, hm[c][1]), hm[c][4], hm[c][5], (T.get(c) or [None] * 7)[5], (T.get(c) or [None] * 7)[6], (T.get(c) or [None, None])[1]] for c in m],
                        chg=round(chg, 2) if chg is not None else None, r5=round(st.mean(r5), 1) if r5 else None, r20=round(st.mean(r20), 1) if r20 else None,
                        up=sum(1 for c in m if (hm[c][4] or 0) > 0), n_=len(m), inst=round(inst, 1), sig=sig, lead=[lead[0], lead[-1]]))
    out.sort(key=lambda x: -(x["chg"] or -99))
    fh.save(os.path.join(DATA, "concepts.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), d=(L("heatmap.json", {}) or {}).get("date"), c=out,
            note="族群成分股依公開報導整理，僅供參考；今日漲跌以市值加權，5/20 日漲跌為成分股平均；法人＝外資＋投信近 5 日買賣超金額（張數×今日收盤估算）。"))
    print("concepts.json:", len(out), "個族群;最強", out[0]["n"] if out else None, out[0]["chg"] if out else None, "最弱", out[-1]["n"] if out else None, out[-1]["chg"] if out else None)

if __name__ == "__main__":
    main()
