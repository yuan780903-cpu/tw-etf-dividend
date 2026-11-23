// 一鍵更新:網頁按鈕 -> 這個 Worker -> 觸發 GitHub Actions 的 update.yml(雲端重抓全部資料)
// 需要 Worker 秘密變數 GH_TOKEN:GitHub「細粒度權杖」,只授權 tw-etf-dividend 這個 repo 的 Actions: Read and write
// 防濫用:已有更新在跑、或 10 分鐘內剛觸發過,就不再觸發
const REPO = "yuan780903-cpu/tw-etf-dividend", WF = "update.yml";
const ALLOW = ["https://yuan780903-cpu.github.io", "http://localhost:8770"];
const cors = o => ({ "Access-Control-Allow-Origin": ALLOW.includes(o) ? o : ALLOW[0], "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type", "Content-Type": "application/json; charset=utf-8" });
const gh = (env, path, init = {}) => fetch(`https://api.github.com/repos/${REPO}${path}`, { ...init,
  headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "etf-update-worker", "X-GitHub-Api-Version": "2022-11-28" } });

async function latest(env) {
  const r = await gh(env, `/actions/workflows/${WF}/runs?per_page=1`);
  if (!r.ok) throw new Error(`GitHub ${r.status}`);
  const run = (await r.json()).workflow_runs?.[0];
  return run ? { id: run.id, status: run.status, conclusion: run.conclusion, created: run.created_at, url: run.html_url } : null;
}

/* 自動補跑(看門狗):每個交易日 18:30、23:30、隔天 07:30(台北)檢查網站資料;
   今天的更新沒成功(健康報告不是今天的)或有嚴重錯誤,且 3 小時內沒跑過 → 自動觸發一次更新 */
async function watchdog(env) {
  const tpe = new Date(Date.now() + 8 * 3600e3), day = tpe.toISOString().slice(0, 10), h = tpe.getUTCHours();
  const want = h < 12 ? new Date(tpe.getTime() - 864e5).toISOString().slice(0, 10) : day;     // 早上檢查的是「昨天」的更新
  const wd = new Date(want + "T00:00:00Z").getUTCDay(); if (wd == 0 || wd == 6) return { skip: "週末" };
  let hl = null;
  try { hl = await (await fetch(`https://raw.githubusercontent.com/${REPO}/main/data/health.json?t=${Date.now()}`, { headers: { "User-Agent": "etf-watchdog" } })).json(); } catch (e) {}
  const stale = !hl || String(hl.updated || "").slice(0, 10) < want, bad = hl && hl.overall == "error";
  if (!stale && !bad) return { ok: true, health: hl.overall };
  const run = await latest(env);
  if (run && run.status != "completed") return { skip: "更新進行中" };
  if (run && Date.now() - Date.parse(run.created) < 3 * 3600e3) return { skip: "3 小時內已跑過" };
  const r = await gh(env, `/actions/workflows/${WF}/dispatches`, { method: "POST", body: JSON.stringify({ ref: "main", inputs: { mode: "full" } }) });
  return { dispatched: r.status == 204, why: stale ? "資料過期" : "健康檢查有錯誤" };
}

/* PTT 股版熱度:PTT 擋雲端主機,改由站長 iPhone「捷徑」讀 PTT 網頁後上傳到這裡(要金鑰 PTT_KEY)
   POST /ptt/up?k=金鑰   內容=一頁 PTT 股版列表 HTML → 只留標題/連結/推文數/日期(不收帳號),回傳「下一頁(較舊)」網址給捷徑
   POST /ptt/done?k=金鑰 → 觸發一次只算 PTT 的小更新(約 1 分鐘)
   GET  /ptt/posts       → 雲端 fetch_ptt.py 取用(最新 400 篇) */
const PTT = "https://www.ptt.cc", PTT_FIRST = PTT + "/bbs/Stock/index.html";
const unesc = s => s.replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n)).replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const pttTs = u => +((u.match(/M\.(\d+)\./) || [])[1] || 0);
const tpeNow = () => new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 16).replace("T", " ");
function pttParse(h) {
  const posts = [];
  for (let blk of h.split('<div class="r-ent">').slice(1)) {        // 每篇一段(到下一篇或置底分隔線為止)
    blk = blk.split('<div class="r-list-sep"')[0]; const t = blk.match(/<a href="(\/bbs\/Stock\/M\.[^"]+)">([^<]+)<\/a>/); if (!t) continue;
    const nr = blk.match(/<div class="nrec">(?:<span[^>]*>)?([^<]*)/), n = (nr ? nr[1] : "").trim();
    const d = blk.match(/<div class="date">\s*([\d\/]+)/);
    posts.push({ u: PTT + t[1], t: unesc(t[2]).trim(), p: n == "爆" ? 100 : n.startsWith("X") ? -10 : /^\d+$/.test(n) ? +n : 0, d: d ? d[1].trim() : "" });
  }
  const prev = h.match(/href="(\/bbs\/Stock\/index\d+\.html)">&lsaquo;/);
  return { posts, next: prev ? PTT + prev[1] : null };
}
async function pttRoute(req, env, url, H) {
  const T = (s, st = 200) => new Response(s, { status: st, headers: { ...H, "Content-Type": "text/plain; charset=utf-8" } });
  const J = (o, st = 200) => new Response(JSON.stringify(o), { status: st, headers: H });
  if (!env.PTTKV) return J({ status: "no-kv" }, 503);
  if (url.pathname == "/ptt/posts") {
    const keys = (await env.PTTKV.list({ prefix: "pg:" })).keys, all = {}; let updated = null;
    for (const v of await Promise.all(keys.map(k => env.PTTKV.get(k.name, "json")))) {
      if (!v) continue; if (!updated || v.at > updated) updated = v.at;
      for (const x of v.posts) if (!all[x.u] || all[x.u].at <= v.at) all[x.u] = { ...x, at: v.at };   // 同一篇以最新一次上傳的推文數為準
    }
    const posts = Object.values(all).sort((a, b) => pttTs(b.u) - pttTs(a.u)).slice(0, 400).map(({ at, ...x }) => x);
    return J({ updated, n: posts.length, pages: keys.length, posts });
  }
  if (!env.PTT_KEY || url.searchParams.get("k") != env.PTT_KEY) return T("金鑰不對", 403);
  if (url.pathname == "/ptt/up") {
    let h = ""; const ct = req.headers.get("Content-Type") || "";
    if (ct.includes("multipart/form-data")) { const f = await req.formData(); for (const [, v] of f) { h = typeof v == "string" ? v : await v.text(); break; } }
    else h = await req.text();
    if (h.length > 800000) return T("太大", 413);
    const { posts, next } = pttParse(h);
    if (!posts.length) return T(PTT_FIRST);                 // 讀到的不是股版列表:回到第一頁
    const pg = next ? +next.match(/index(\d+)/)[1] + 1 : 0;   // 這一頁的頁碼(每頁存一筆,避免同一筆一秒內重複寫入被擋)
    await env.PTTKV.put("pg:" + pg, JSON.stringify({ at: tpeNow(), posts }), { expirationTtl: 3 * 86400 });
    return T(next || PTT_FIRST);
  }
  if (url.pathname == "/ptt/done") {
    const run = await latest(env);
    if (run && run.status != "completed") return T("雲端正在更新,會一併用到這次的 PTT 資料");
    const r = await gh(env, `/actions/workflows/${WF}/dispatches`, { method: "POST", body: JSON.stringify({ ref: "main", inputs: { mode: "ptt" } }) });
    return T(r.status == 204 ? "已通知網站更新 PTT 熱度(約 1～2 分鐘)" : "通知失敗 " + r.status, r.status == 204 ? 200 : 502);
  }
  return T("?", 404);
}

export default {
  async scheduled(ev, env, ctx) { if (env.GH_TOKEN) ctx.waitUntil(watchdog(env)); },
  async fetch(req, env) {
    const o = req.headers.get("Origin") || "", H = cors(o), url = new URL(req.url);
    if (req.method == "OPTIONS") return new Response(null, { headers: H });
    const J = (obj, s = 200) => new Response(JSON.stringify(obj), { status: s, headers: H });
    if (!env.GH_TOKEN) return J({ status: "no-token", msg: "Worker 尚未設定 GH_TOKEN" }, 503);
    try {
      if (url.pathname == "/status") return J({ status: "ok", run: await latest(env) });
      if (url.pathname == "/watchdog") return J(await watchdog(env));
      if (url.pathname.startsWith("/ptt/")) return await pttRoute(req, env, url, H);
      if (url.pathname == "/dispatch" && req.method == "POST") {
        if (o && !ALLOW.includes(o)) return J({ status: "forbidden" }, 403);
        const run = await latest(env);
        if (run && run.status != "completed") return J({ status: "running", run });
        if (run && Date.now() - Date.parse(run.created) < 10 * 60e3) return J({ status: "recent", run });
        let mode = "quick"; try { const b = await req.clone().json(); if (b && b.mode == "full") mode = "full"; } catch (e) {}   // 網頁一鍵更新預設快速模式
        const r = await gh(env, `/actions/workflows/${WF}/dispatches`, { method: "POST", body: JSON.stringify({ ref: "main", inputs: { mode } }) });
        if (r.status != 204) return J({ status: "error", code: r.status, msg: await r.text() }, 502);
        return J({ status: "started", mode });
      }
      return J({ status: "ok", msg: "POST /dispatch 觸發更新;GET /status 查進度" });
    } catch (e) { return J({ status: "error", msg: String(e) }, 502); }
  },
};
