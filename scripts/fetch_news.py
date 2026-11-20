"""國內外盤勢快訊 -> data/news.json(只存標題、來源、時間、連結;內文請點原文)
來源:Yahoo 股市 RSS(台股、國際、ETF基金、研究報告)
"""
import json, os, re, sys, html, datetime as dt, urllib.request, email.utils
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_history as fh
FEEDS = {"tw": "tw-market", "intl": "intl-markets", "fund": "funds-news", "res": "research"}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124 Safari/537.36"}

def parse(xml):
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        g = lambda t: (re.search(rf"<{t}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{t}>", it, re.S) or [None, ""])[1].strip()
        title, link, pub, desc = html.unescape(g("title")), g("link"), g("pubDate"), g("description")
        src = re.match(r"\s*\[([^\]]{1,20})\]", html.unescape(desc))
        try: ts = int(email.utils.parsedate_to_datetime(pub).timestamp())
        except Exception: ts = 0
        if title and link: out.append(dict(t=title, u=link, s=src.group(1) if src else "Yahoo股市", ts=ts))
    return out

def main():
    res = {}
    for k, cat in FEEDS.items():
        try:
            xml = urllib.request.urlopen(urllib.request.Request(f"https://tw.stock.yahoo.com/rss?category={cat}", headers=UA), timeout=30).read().decode("utf-8", "ignore")
            res[k] = parse(xml)[:40]
        except Exception as e:
            print("news", k, "失敗", e); res[k] = []
    fh.save(os.path.join(fh.DATA, "news.json"), dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), feeds=res))
    print("news.json:", "、".join(f"{k} {len(v)}" for k, v in res.items()))

if __name__ == "__main__":
    main()
