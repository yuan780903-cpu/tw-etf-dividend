/* 巴菲遠・盤中雷達雲端推播 Worker
 * - 網站把「雷達名單 + 警示條件 + 推播訂閱」存到這裡(POST /sub)
 * - Cron 盤中每分鐘抓證交所即時報價,依條件判斷,觸發就送 Web Push(網站關閉也收得到)
 * - 推播不帶內容(免加密),手機收到後由 Service Worker 呼叫 GET /pending 取得警示文字再跳通知
 * 秘密:VAPID_PRIVATE_JWK(wrangler secret)。公開金鑰放在 wrangler.toml 的 VAPID_PUBLIC。
 */
const ORIGINS = ["https://yuan780903-cpu.github.io", "http://localhost:8770"];
const PUSH_HOSTS = /^(fcm\.googleapis\.com|android\.googleapis\.com|updates\.push\.services\.mozilla\.com|web\.push\.apple\.com|[a-z0-9-]+\.notify\.windows\.com|[a-z0-9-]+\.push\.apple\.com)$/;
const UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"};
const YUA = {"User-Agent": "Mozilla/5.0"};   // Yahoo 會擋完整瀏覽器字串(429),用簡短版
const DEF = {drop: 2, win: 15, pct: -5, lim: -8, sell: 3, up: true, brief: true};

const cors = req => { const o = req.headers.get("Origin") || ""; return {"Access-Control-Allow-Origin": ORIGINS.includes(o) ? o : ORIGINS[0], "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type", "Vary": "Origin"}; };
const J = (req, d, s = 200) => new Response(JSON.stringify(d), {status: s, headers: {"Content-Type": "application/json; charset=utf-8", ...cors(req)}});
const tpe = () => { const d = new Date(Date.now() + 8 * 3600e3); return {day: d.toISOString().slice(0, 10), m: d.getUTCHours() * 60 + d.getUTCMinutes(), wd: d.getUTCDay(), hm: d.toISOString().slice(11, 19)}; };
const b64u = buf => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const b64uStr = s => b64u(new TextEncoder().encode(s));
const okEndpoint = ep => { try { const u = new URL(ep); return u.protocol == "https:" && PUSH_HOSTS.test(u.hostname); } catch (e) { return false; } };
const cleanCodes = a => [...new Set((Array.isArray(a) ? a : []).map(x => String(x).toUpperCase()).filter(x => /^[0-9A-Z]{4,6}$/.test(x)))].slice(0, 80);

/* ---------- Web Push(VAPID,不帶內容)---------- */
let KEY = null; const JWTC = {};
async function vapid(env, aud){
  const c = JWTC[aud]; if (c && c.exp > Date.now() / 1000 + 600) return c.t;
  KEY = KEY || await crypto.subtle.importKey("jwk", JSON.parse(env.VAPID_PRIVATE_JWK), {name: "ECDSA", namedCurve: "P-256"}, false, ["sign"]);
  const exp = Math.floor(Date.now() / 1000) + 12 * 3600, data = b64uStr(JSON.stringify({typ: "JWT", alg: "ES256"})) + "." + b64uStr(JSON.stringify({aud, exp, sub: "https://yuan780903-cpu.github.io/tw-etf-dividend/"}));
  const sig = await crypto.subtle.sign({name: "ECDSA", hash: "SHA-256"}, KEY, new TextEncoder().encode(data));
  const t = data + "." + b64u(sig); JWTC[aud] = {t, exp}; return t;
}
async function push(env, sub){
  const aud = new URL(sub.endpoint).origin, t = await vapid(env, aud);
  const r = await fetch(sub.endpoint, {method: "POST", headers: {Authorization: `vapid t=${t}, k=${env.VAPID_PUBLIC}`, TTL: "600", Urgency: "high", "Content-Length": "0"}});
  if (r.status == 404 || r.status == 410) { await env.DB.prepare("DELETE FROM subs WHERE id=?").bind(sub.id).run(); return "gone"; }
  if (!r.ok) await env.DB.prepare("UPDATE subs SET fails=fails+1 WHERE id=?").bind(sub.id).run();
  return r.status;
}

/* ---------- 行情 ---------- */
async function mis(chs){
  const out = {};
  for (let i = 0; i < chs.length; i += 40) {
    try {
      const r = await fetch("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?json=1&delay=0&ex_ch=" + chs.slice(i, i + 40).join("|"), {headers: {...UA, Referer: "https://mis.twse.com.tw/stock/index.jsp"}});
      const d = JSON.parse((await r.text()).trim());
      for (const q of d.msgArray || []) {
        const n = x => { const v = parseFloat(x); return isNaN(v) ? null : v; }, sum = s => (s || "").split("_").filter(Boolean).reduce((a, b) => a + (parseFloat(b) || 0), 0);
        const z = n(q.z), bb = n((q.b || "").split("_")[0]), aa = n((q.a || "").split("_")[0]), live = z ?? (bb && aa ? (bb + aa) / 2 : bb ?? aa);
        if (live && n(q.y)) out[String(q.c)] = {px: live, y: n(q.y), o: n(q.o), h: n(q.h), l: n(q.l), bid: sum(q.g), ask: sum(q.f), dn: n(q.w), nm: q.n, ex: q.ex};
      }
    } catch (e) {}
  }
  return out;
}
async function pivot(c, mk){
  for (const suf of mk == "otc" ? ["TWO", "TW"] : ["TW", "TWO"]) {
    try {
      const r = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${c}.${suf}?range=10d&interval=1d`, {headers: YUA});
      if (!r.ok) continue; const x = (await r.json()).chart.result[0], qt = x.indicators.quote[0], off = x.meta.gmtoffset || 28800, today = tpe().day;
      const rows = x.timestamp.map((t, i) => [new Date((t + off) * 1000).toISOString().slice(0, 10), qt.high[i], qt.low[i], qt.close[i]]).filter(r => r[3] != null && r[0] < today);
      const y = rows[rows.length - 1]; if (!y) continue; const [, H, L, C] = y, P = (H + L + C) / 3;
      return {P, R1: 2 * P - L, S1: 2 * P - H, R2: P + (H - L), S2: P - (H - L), mk: suf == "TWO" ? "otc" : "tse"};
    } catch (e) {}
  }
  return {none: 1};
}

/* ---------- 警示規則(與網站盤中雷達一致;雲端版沒有均價線)---------- */
function rules(c, q, st, cf, ref, m){
  const A = [], px = q.px, pct = (px / q.y - 1) * 100, prev = st.prev[c], pv = st.piv[c] || {}, orb = st.orb[c], N = `${c} ${q.nm || ""}`.trim(), F = x => (+x).toFixed(x >= 100 ? 1 : 2);
  const S = (st.smp[c] || []).filter(x => Date.now() - x[0] <= cf.win * 60e3), hi = S.length ? Math.max(...S.map(x => x[1])) : px, lo0 = S.length ? S[0][1] : px;
  const dn = lv => lv && prev != null && prev >= lv && px < lv, up = lv => lv && prev != null && prev <= lv && px > lv, ratio = q.ask > 0 ? q.bid / q.ask : null;
  const add = (k, title, body, bad = 1) => A.push({k, title, body, bad});
  if ((px / hi - 1) * 100 <= -cf.drop) add("drop:" + Math.floor(m / 20), `⚠️ ${N} 急跌`, `${cf.win} 分鐘內從 ${F(hi)} 跌到 ${F(px)}（${((px / hi - 1) * 100).toFixed(1)}%），今日 ${pct.toFixed(2)}%`);
  if (ratio != null && ratio < 1 / cf.sell && pct < 0 && q.o && px < q.o) add("sell:" + Math.floor(m / 30), `🔻 ${N} 大量賣壓`, `委賣是委買的 ${(1 / ratio).toFixed(1)} 倍，股價 ${F(px)} 低於開盤，可能續跌`);
  if (m > 555 && orb && dn(orb[1])) add("orl", `📉 ${N} 跌破開盤區間`, `跌破開盤 15 分鐘低點 ${F(orb[1])}，當沖偏空`);
  if (dn(pv.S1)) add("s1", `📉 ${N} 跌破支撐 S1`, `跌破今日支撐 ${F(pv.S1)}（下一支撐 S2 ${F(pv.S2)}）`);
  if (ref && dn(ref.ma20)) add("ma20", `📉 ${N} 跌破月線`, `跌破 20 日均線 ${F(ref.ma20)}，中期轉弱`);
  if (ref && dn(ref.sup)) add("sup", `🛑 ${N} 跌破 20 日支撐`, `跌破近 20 日最低收盤 ${F(ref.sup)}，持股者留意停損`);
  const pxr = cf.px && cf.px[c];             // 自訂價位提醒 [跌破, 漲過]
  if (pxr && pxr[0] && px <= pxr[0]) add("plo", `🎯 ${N} 跌到你設定的價位`, `現價 ${F(px)}，已跌破你設的 ${F(pxr[0])} 元（今日 ${pct.toFixed(2)}%）`);
  if (pxr && pxr[1] && px >= pxr[1]) add("phi", `🎯 ${N} 漲到你設定的價位`, `現價 ${F(px)}，已漲過你設的 ${F(pxr[1])} 元（今日 ${pct.toFixed(2)}%）`, 0);
  if (pct <= cf.pct) add("pct", `⚠️ ${N} 跌幅擴大`, `今日 ${pct.toFixed(2)}%（${F(px)}）`);
  if (pct <= cf.lim) add("lim", `🚨 ${N} 接近跌停`, `今日 ${pct.toFixed(2)}%，跌停價 ${F(q.dn || q.y * .9)}`);
  if (cf.up) {
    if (m > 555 && orb && up(orb[0])) add("orh", `🚀 ${N} 突破開盤區間`, `突破開盤 15 分鐘高點 ${F(orb[0])}，當沖偏多`, 0);
    if (up(pv.R1)) add("r1", `🚀 ${N} 站上壓力 R1`, `站上今日壓力 ${F(pv.R1)}（下一壓力 R2 ${F(pv.R2)}）`, 0);
    if (ref && up(ref.res)) add("res", `🚀 ${N} 突破 20 日高點`, `突破近 20 日最高收盤 ${F(ref.res)}`, 0);
    if ((px / lo0 - 1) * 100 >= cf.drop && S.length > 1) add("jump:" + Math.floor(m / 20), `📈 ${N} 急漲`, `${cf.win} 分鐘內 +${((px / lo0 - 1) * 100).toFixed(1)}%，今日 ${pct.toFixed(2)}%`, 0);
  }
  return A;
}

/* ---------- 每日晨報(08:30)/收盤摘要(13:45)---------- */
async function spark(syms){
  try { const r = await fetch("https://query1.finance.yahoo.com/v7/finance/spark?symbols=" + syms.map(encodeURIComponent).join(",") + "&range=5d&interval=1d", {headers: YUA});
    const o = {}; for (const x of (await r.json()).spark.result) { const R = x.response[0], m = R.meta, cl = ((R.indicators || {}).quote || [{}])[0].close || [];
      const c = cl.filter(v => v != null), pv = m.previousClose ?? (c.length > 1 ? c[c.length - 2] : null), px = c.length ? c[c.length - 1] : m.regularMarketPrice;
      o[x.symbol] = {px, chg: pv ? (px / pv - 1) * 100 : null}; } return o; } catch (e) { return {}; }
}
async function brief(env, subs, T){
  const DB = env.DB, am = T.m < 600, key = am ? "brief-am" : "brief-pm", P = (x, d = 1) => x == null ? "—" : (x > 0 ? "+" : "") + x.toFixed(d) + "%";
  let title, body0;
  if (am) {
    const y = await spark(["^GSPC", "^IXIC", "^SOX", "TSM", "TWD=X", "^VIX"]); const g = k => y[k] || {};
    title = `☀️ 巴菲遠晨報 ${T.day.slice(5).replace("-", "/")}`;
    body0 = `美股：標普 ${P(g("^GSPC").chg)}、那斯達克 ${P(g("^IXIC").chg)}、費半 ${P(g("^SOX").chg)}；台積電 ADR ${P(g("TSM").chg)}；VIX ${g("^VIX").px ? g("^VIX").px.toFixed(1) : "—"}；美元兌台幣 ${g("TWD=X").px ? g("TWD=X").px.toFixed(3) : "—"}。`;
  } else {
    const q = await mis(["tse_t00.tw", "otc_o00.tw"]); const t = q["t00"], o = q["o00"];
    title = `🔔 巴菲遠收盤摘要 ${T.day.slice(5).replace("-", "/")}`;
    body0 = t ? `加權 ${t.px.toFixed(0)}（${P((t.px / t.y - 1) * 100, 2)}）${o ? `、櫃買 ${o.px.toFixed(2)}（${P((o.px / o.y - 1) * 100, 2)}）` : ""}。` : "今日收盤資料暫時抓不到。";
  }
  const codes = [...new Set(subs.flatMap(s => JSON.parse(s.codes || "[]")))].slice(0, 120);
  const Q = am ? {} : await mis(codes.flatMap(c => [`tse_${c}.tw`, `otc_${c}.tw`]));
  for (const s of subs) {
    const cf = Object.assign({}, DEF, JSON.parse(s.cfg || "{}")); if (!cf.brief) continue;
    const r = await DB.prepare("INSERT OR IGNORE INTO fired(sub,k,day,ts) VALUES(?,?,?,?)").bind(s.id, key, T.day, Date.now()).run(); if (!r.meta.changes) continue;
    let body = body0;
    if (!am) {
      const mine = JSON.parse(s.codes || "[]").map(c => Q[c] ? [c, (Q[c].px / Q[c].y - 1) * 100, Q[c].nm] : null).filter(Boolean).sort((a, b) => b[1] - a[1]);
      if (mine.length) body += ` 你的雷達：${mine.slice(0, 3).map(x => `${x[2] || x[0]} ${P(x[1])}`).join("、")}${mine.length > 3 ? `；最弱 ${mine.slice(-2).map(x => `${x[2] || x[0]} ${P(x[1])}`).join("、")}` : ""}。`;
      const n = await DB.prepare("SELECT COUNT(*) n FROM alerts WHERE sub=? AND ts>? AND code!='BRIEF'").bind(s.id, Date.now() - 6 * 3600e3).first(); body += ` 今天共 ${n ? n.n : 0} 則盤中警示。`;
    } else body += ` 今天 09:00 開盤，雷達監控中 ${JSON.parse(s.codes || "[]").length} 檔。`;
    await DB.prepare("INSERT INTO alerts(sub,ts,code,title,body,bad) VALUES(?,?,?,?,?,0)").bind(s.id, Date.now(), "BRIEF", title, body).run();
    await push(env, s);
  }
}

async function run(env){
  const T = tpe(); if (!(T.wd >= 1 && T.wd <= 5) || T.m < 480 || (T.m > 812 && T.m != 825)) return {skip: "非交易時間"};
  const DB = env.DB, subs = (await DB.prepare("SELECT * FROM subs").all()).results || [];
  if (T.m == 480) { await DB.prepare("DELETE FROM alerts WHERE ts < ?").bind(Date.now() - 7 * 864e5).run(); await DB.prepare("DELETE FROM fired WHERE day < ?").bind(new Date(Date.now() - 3 * 864e5).toISOString().slice(0, 10)).run(); }
  if (!subs.length) return {subs: 0};
  if (T.m == 510 || T.m == 825) { await brief(env, subs, T); if (T.m == 825) return {brief: "pm"}; }
  const codes = [...new Set(subs.flatMap(s => JSON.parse(s.codes || "[]")))].slice(0, 150), key = "day:" + T.day;
  const row = await DB.prepare("SELECT v FROM state WHERE k=?").bind(key).first();
  const st = Object.assign({piv: {}, smp: {}, prev: {}, orb: {}, mk: {}}, row ? JSON.parse(row.v) : {});
  let n = 0; for (const c of codes) { if (st.piv[c] || n >= 12) continue; st.piv[c] = await pivot(c, st.mk[c]); if (st.piv[c].mk) st.mk[c] = st.piv[c].mk; n++; }   // 每分鐘最多補 12 檔樞紐點
  if (T.m < 540) { await DB.prepare("INSERT OR REPLACE INTO state(k,v,ts) VALUES(?,?,?)").bind(key, JSON.stringify(st), Date.now()).run(); return {pre: true, piv: Object.keys(st.piv).length}; }
  const Q = await mis(codes.flatMap(c => st.mk[c] ? [`${st.mk[c]}_${c}.tw`] : [`tse_${c}.tw`, `otc_${c}.tw`]));
  const now = Date.now(); let fired = 0, pushed = 0;
  for (const [c, q] of Object.entries(Q)) { if (q.ex) st.mk[c] = q.ex; const S = st.smp[c] = (st.smp[c] || []).filter(x => now - x[0] <= 40 * 60e3); S.push([now, q.px]); if (T.m <= 555 && q.h && q.l) st.orb[c] = [q.h, q.l]; }
  for (const s of subs) {
    const cf = Object.assign({}, DEF, JSON.parse(s.cfg || "{}")), refs = JSON.parse(s.refs || "{}"), mine = JSON.parse(s.codes || "[]"); let neu = 0;
    for (const c of mine) {
      const q = Q[c]; if (!q) continue;
      for (const a of rules(c, q, st, cf, refs[c], T.m)) {
        const r = await DB.prepare("INSERT OR IGNORE INTO fired(sub,k,day,ts) VALUES(?,?,?,?)").bind(s.id, c + ":" + a.k, T.day, now).run();
        if (!r.meta.changes) continue;
        await DB.prepare("INSERT INTO alerts(sub,ts,code,title,body,bad) VALUES(?,?,?,?,?,?)").bind(s.id, now, c, a.title, a.body, a.bad).run(); neu++; fired++;
      }
    }
    if (neu) { await push(env, s); pushed++; }
  }
  for (const [c, q] of Object.entries(Q)) st.prev[c] = q.px;
  await DB.prepare("INSERT OR REPLACE INTO state(k,v,ts) VALUES(?,?,?)").bind(key, JSON.stringify(st), now).run();
  return {quotes: Object.keys(Q).length, fired, pushed};
}

export default {
  async fetch(req, env){
    const u = new URL(req.url), p = u.pathname;
    if (req.method == "OPTIONS") return new Response(null, {headers: cors(req)});
    try {
      if (p == "/vapid") return J(req, {key: env.VAPID_PUBLIC});
      if (p == "/sub" && req.method == "POST") {
        const b = await req.json(); if (!okEndpoint(b.endpoint)) return J(req, {error: "不支援的推播服務"}, 400);
        const ex = await env.DB.prepare("SELECT id FROM subs WHERE endpoint=?").bind(b.endpoint).first(), id = ex ? ex.id : crypto.randomUUID(), now = Date.now();
        const refs = {}; for (const [c, r] of Object.entries(b.refs || {})) if (/^[0-9A-Z]{4,6}$/.test(c) && r) refs[c] = {ma20: +r.ma20 || null, sup: +r.sup || null, res: +r.res || null};
        const cfg = {}; for (const k of Object.keys(DEF)) if (b.cfg && b.cfg[k] != null) cfg[k] = typeof DEF[k] == "boolean" ? !!b.cfg[k] : +b.cfg[k];
        if (b.cfg && b.cfg.px && typeof b.cfg.px == "object") { cfg.px = {}; for (const [c, v] of Object.entries(b.cfg.px).slice(0, 80)) if (/^[0-9A-Z]{4,6}$/.test(c) && Array.isArray(v)) cfg.px[c] = [+v[0] || 0, +v[1] || 0]; }
        await env.DB.prepare("INSERT INTO subs(id,endpoint,codes,cfg,refs,created,updated,fails) VALUES(?,?,?,?,?,?,?,0) ON CONFLICT(endpoint) DO UPDATE SET codes=excluded.codes,cfg=excluded.cfg,refs=excluded.refs,updated=excluded.updated,fails=0")
          .bind(id, b.endpoint, JSON.stringify(cleanCodes(b.codes)), JSON.stringify(cfg), JSON.stringify(refs), now, now).run();
        return J(req, {ok: true, id, n: cleanCodes(b.codes).length});
      }
      if (p == "/unsub" && req.method == "POST") { const b = await req.json(); await env.DB.prepare("DELETE FROM subs WHERE endpoint=?").bind(b.endpoint || "").run(); return J(req, {ok: true}); }
      if (p == "/test" && req.method == "POST") {
        const b = await req.json(), s = await env.DB.prepare("SELECT * FROM subs WHERE endpoint=?").bind(b.endpoint || "").first(); if (!s) return J(req, {error: "尚未訂閱"}, 404);
        await env.DB.prepare("INSERT INTO alerts(sub,ts,code,title,body,bad) VALUES(?,?,?,?,?,1)").bind(s.id, Date.now(), "TEST", "✅ 雲端推播測試成功", `網站關閉時也會收到盤中警示（雷達 ${JSON.parse(s.codes).length} 檔）`).run();
        return J(req, {ok: true, status: await push(env, s)});
      }
      if (p == "/pending") {                       // Service Worker 收到推播後來拿警示文字
        const s = await env.DB.prepare("SELECT id FROM subs WHERE endpoint=?").bind(u.searchParams.get("ep") || "").first(); if (!s) return J(req, {items: []});
        const R = (await env.DB.prepare("SELECT id,ts,code,title,body,bad FROM alerts WHERE sub=? AND sent=0 AND ts>? ORDER BY ts DESC LIMIT 6").bind(s.id, Date.now() - 30 * 60e3).all()).results || [];
        if (R.length) await env.DB.prepare(`UPDATE alerts SET sent=1 WHERE sub=? AND id IN (${R.map(() => "?").join(",")})`).bind(s.id, ...R.map(r => r.id)).run();
        return J(req, {items: R});
      }
      if (p == "/recent") {
        const s = await env.DB.prepare("SELECT id,codes,updated FROM subs WHERE endpoint=?").bind(u.searchParams.get("ep") || "").first(); if (!s) return J(req, {sub: false, items: []});
        const R = (await env.DB.prepare("SELECT ts,code,title,body,bad FROM alerts WHERE sub=? ORDER BY ts DESC LIMIT 50").bind(s.id).all()).results || [];
        return J(req, {sub: true, n: JSON.parse(s.codes).length, updated: s.updated, items: R});
      }
      if (p == "/status") { const c = await env.DB.prepare("SELECT COUNT(*) n FROM subs").first(), t = await env.DB.prepare("SELECT ts FROM state ORDER BY ts DESC LIMIT 1").first(); return J(req, {subs: c.n, lastRun: t ? new Date(t.ts).toISOString() : null}); }
      return J(req, {name: "巴菲遠盤中雷達推播"});
    } catch (e) { return J(req, {error: e.message}, 500); }
  },
  async scheduled(ev, env, ctx){ ctx.waitUntil(run(env)); },
};
