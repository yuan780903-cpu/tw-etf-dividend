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
