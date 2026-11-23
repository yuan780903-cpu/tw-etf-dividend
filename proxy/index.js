/* crm-proxy 重建版(原版是在 Cloudflare 網頁直接建的,原始碼不在 repo)
 * 用法:https://crm-proxy.<子網域>.workers.dev/?url=<urlencoded 目標網址>
 * 行為:轉發 GET 請求,加上 Access-Control-Allow-Origin: *,供網頁抓 Yahoo、證交所 MIS、新聞 RSS、CRM 智慧搜尋使用
 */
const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36";
export default {
  async fetch(req){
    const cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,OPTIONS", "Access-Control-Allow-Headers": "*"};
    if (req.method == "OPTIONS") return new Response(null, {headers: cors});
    const target = new URL(req.url).searchParams.get("url");
    if (!target || !/^https?:\/\//.test(target)) return new Response("用法:?url=<目標網址>", {status: 400, headers: cors});
    const h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"};
    if (target.includes("mis.twse.com.tw")) h.Referer = "https://mis.twse.com.tw/stock/index.jsp";
    try {
      const r = await fetch(target, {headers: h, redirect: "follow", cf: {cacheTtl: 0}});
      const out = new Headers(cors); out.set("Content-Type", r.headers.get("Content-Type") || "text/plain; charset=utf-8");
      return new Response(r.body, {status: r.status, headers: out});
    } catch (e) { return new Response("代理失敗:" + e.message, {status: 502, headers: cors}); }
  },
};
