// 一鍵更新:網頁按鈕 -> 這個 Worker -> 觸發 GitHub Actions 的 update.yml(雲端重抓全部資料)
// 需要 Worker 秘密變數 GH_TOKEN:GitHub「細粒度權杖」,只授權 tw-etf-dividend 這個 repo 的 Actions: Read and write
// 防濫用:已有更新在跑、或 10 分鐘內剛觸發過,就不再觸發
const REPO = "yuan780903-cpu/tw-etf-dividend", WF = "update.yml";
const ALLOW = ["https://yuan780903-cpu.github.io", "http://localhost:8770"];
const cors = o => ({ "Access-Control-Allow-Origin": ALLOW.includes(o) ? o : ALLOW[0], "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Content-Type": "application/json; charset=utf-8" });
const gh = (env, path, init = {}) => fetch(`https://api.github.com/repos/${REPO}${path}`, { ...init,
  headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "etf-update-worker", "X-GitHub-Api-Version": "2022-11-28" } });

async function latest(env) {
  const r = await gh(env, `/actions/workflows/${WF}/runs?per_page=1`);
  if (!r.ok) throw new Error(`GitHub ${r.status}`);
  const run = (await r.json()).workflow_runs?.[0];
  return run ? { id: run.id, status: run.status, conclusion: run.conclusion, created: run.created_at, url: run.html_url } : null;
}

export default {
  async fetch(req, env) {
    const o = req.headers.get("Origin") || "", H = cors(o), url = new URL(req.url);
    if (req.method == "OPTIONS") return new Response(null, { headers: H });
    const J = (obj, s = 200) => new Response(JSON.stringify(obj), { status: s, headers: H });
    if (!env.GH_TOKEN) return J({ status: "no-token", msg: "Worker 尚未設定 GH_TOKEN" }, 503);
    try {
      if (url.pathname == "/status") return J({ status: "ok", run: await latest(env) });
      if (url.pathname == "/dispatch" && req.method == "POST") {
        if (o && !ALLOW.includes(o)) return J({ status: "forbidden" }, 403);
        const run = await latest(env);
        if (run && run.status != "completed") return J({ status: "running", run });
        if (run && Date.now() - Date.parse(run.created) < 10 * 60e3) return J({ status: "recent", run });
        const r = await gh(env, `/actions/workflows/${WF}/dispatches`, { method: "POST", body: JSON.stringify({ ref: "main" }) });
        if (r.status != 204) return J({ status: "error", code: r.status, msg: await r.text() }, 502);
        return J({ status: "started" });
      }
      return J({ status: "ok", msg: "POST /dispatch 觸發更新;GET /status 查進度" });
    } catch (e) { return J({ status: "error", msg: String(e) }, 502); }
  },
};
