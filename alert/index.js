/* 巴菲遠・盤中雷達雲端推播 Worker
 * - 網站把「雷達名單 + 警示條件 + 推播訂閱」存到這裡(POST /sub)
 * - 另有盤勢摘要(晨報/台股開盤/收盤/三大法人/美股開盤/美股收盤,見 SLOTS),存全站時間軸 /briefs 並推播
 * - ⚡ 總經快訊(macRun):美國數據一公布(FRED)、FOMC 決策(聯準會 RSS)、台灣景氣燈號/出口/外銷訂單 → 白話判讀,存 macro 表(GET /macro)並推播
 * - Cron 盤中每分鐘抓證交所即時報價,依條件判斷,觸發就送 Web Push(網站關閉也收得到)
 * - 推播不帶內容(免加密),手機收到後由 Service Worker 呼叫 GET /pending 取得警示文字再跳通知
 * 秘密:VAPID_PRIVATE_JWK(wrangler secret)。公開金鑰放在 wrangler.toml 的 VAPID_PUBLIC。
 */
const ORIGINS = ["https://yuan780903-cpu.github.io", "http://localhost:8770"];
const PUSH_HOSTS = /^(fcm\.googleapis\.com|android\.googleapis\.com|updates\.push\.services\.mozilla\.com|web\.push\.apple\.com|[a-z0-9-]+\.notify\.windows\.com|[a-z0-9-]+\.push\.apple\.com)$/;
const UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"};
const YUA = {"User-Agent": "Mozilla/5.0"};   // Yahoo 會擋完整瀏覽器字串(429),用簡短版
const DEF = {drop: 2, win: 15, pct: -5, lim: -8, sell: 3, up: true, brief: true, b_am: true, b_open: true, b_close: true, b_inst: true, b_uso: true, b_usc: true, b_mac: true};

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
        if (live && n(q.y)) out[String(q.c)] = {px: live, y: n(q.y), o: n(q.o), h: n(q.h), l: n(q.l), bid: sum(q.g), ask: sum(q.f), dn: n(q.w), nm: q.n, ex: q.ex, d: q.d, t: q.t};
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

/* ---------- 盤勢摘要(網站時間軸＋推播)----------
 * ☀️ 晨報 08:30、🔔 台股開盤 09:05、🔔 台股收盤 13:35、🏦 三大法人 15:00 起每 5 分鐘試到有資料
 * 🇺🇸 美股開盤 美東 09:35、美股收盤 美東 16:05(台灣冬令 22:35／05:05,夏令 21:35／04:05,程式自動換算)
 * 晨報、美股收盤都附「💱 美元兌台幣」:升貶幾角、近一個月位置、對台股的白話判讀(fxTwd/fxTxt)
 * 台股休市看證交所休市日；美股休市看最後成交日期不是今天就不發 */
const BKEY = {am: "b_am", open: "b_open", close: "b_close", inst: "b_inst", uso: "b_uso", usc: "b_usc"};
const SLOTS = [["am", "tw", 510, 520, 1], ["open", "tw", 545, 552, 1], ["close", "tw", 815, 825, 1], ["inst", "tw", 900, 960, 5], ["uso", "ny", 575, 590, 1], ["usc", "ny", 965, 990, 1]];
const pc = (x, d = 1) => x == null || !isFinite(x) ? "—" : (x > 0 ? "+" : "") + x.toFixed(d) + "%";
const nf = (x, d = 0) => x == null || !isFinite(x) ? "—" : Number(x).toLocaleString("en-US", {minimumFractionDigits: d, maximumFractionDigits: d});
const yi = x => x == null || !isFinite(x) ? "—" : (x > 0 ? "+" : "") + nf(x, 1);
const md = s => s.slice(5).replace("-", "/");
const chg = q => q && q.y ? (q.px / q.y - 1) * 100 : null;
function nyNow(){
  const d = new Date(), y = d.getUTCFullYear(), sun = (m, n) => { const w = new Date(Date.UTC(y, m, 1)).getUTCDay(); return 1 + (7 - w) % 7 + 7 * (n - 1); };
  const dst = d >= Date.UTC(y, 2, sun(2, 2), 7) && d < Date.UTC(y, 10, sun(10, 1), 6), n = new Date(d.getTime() + (dst ? -4 : -5) * 3600e3);
  return {day: n.toISOString().slice(0, 10), m: n.getUTCHours() * 60 + n.getUTCMinutes(), wd: n.getUTCDay()};
}
async function spark(syms){   // range=1d:previousClose=前一交易日收盤、regularMarketTime=最後成交時間
  try { const r = await fetch("https://query1.finance.yahoo.com/v7/finance/spark?symbols=" + syms.map(encodeURIComponent).join(",") + "&range=1d&interval=5m", {headers: YUA});
    const o = {}; for (const x of (await r.json()).spark.result) { const m = x.response[0].meta, px = m.regularMarketPrice, pv = m.previousClose ?? m.chartPreviousClose;
      const lt = m.regularMarketTime ? new Date((m.regularMarketTime + (m.gmtoffset || 0)) * 1000).toISOString() : "";
      o[x.symbol] = {px, pv, chg: px && pv ? (px / pv - 1) * 100 : null, day: lt.slice(0, 10), hm: lt.slice(11, 16)}; } return o; } catch (e) { return {}; }
}
async function getJ(url, opt = {}){   // 證交所有時會 307 轉址並要求 cookie
  let ck = "";
  for (let i = 0; i < 4; i++) {
    try {
      const r = await fetch(url, {...opt, headers: {...UA, ...(opt.headers || {}), ...(ck ? {Cookie: ck} : {})}, redirect: "manual"});
      if (r.status >= 300 && r.status < 400) { const sc = r.headers.get("set-cookie"); if (sc) ck = sc.split(/,(?=\s*[^;,=\s]+=)/).map(s => s.split(";")[0].trim()).join("; "); const loc = r.headers.get("location"); if (loc) url = new URL(loc, url).href; continue; }
      if (!r.ok) return null; return opt.raw ? new Uint8Array(await r.arrayBuffer()) : await r.json();
    } catch (e) { return null; }
  }
  return null;
}
const num = s => { const v = parseFloat(String(s).replace(/,/g, "")); return isNaN(v) ? 0 : v; };
async function twHoliday(env, day){   // 證交所休市日(含「市場無交易」),一週更新一次
  const y = day.slice(0, 4), k = "hol:" + y, row = await env.DB.prepare("SELECT v,ts FROM state WHERE k=?").bind(k).first();
  let L = row ? JSON.parse(row.v) : null;
  if (!L || Date.now() - row.ts > 7 * 864e5) {
    const j = await getJ(`https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?date=${y}0101&response=json`);
    if (j && Array.isArray(j.data) && j.data.length) { L = j.data.filter(r => !/開始交易|最後交易/.test(r[1])).map(r => r[0]); await env.DB.prepare("INSERT OR REPLACE INTO state(k,v,ts) VALUES(?,?,?)").bind(k, JSON.stringify(L), Date.now()).run(); }
  }
  return !!(L && L.includes(day));
}

/* 美元兌台幣(Yahoo 國際報價 TWD=X):現價、前一日收盤、近一個月高低 → 白話判讀 */
async function fxTwd(){
  const q = (await spark(["TWD=X"]))["TWD=X"] || {}; if (!q.px) return null;
  let hi = null, lo = null;
  try { const r = await fetch("https://query1.finance.yahoo.com/v8/finance/chart/TWD=X?range=1mo&interval=1d", {headers: YUA});
    const cl = ((await r.json()).chart.result[0].indicators.quote[0].close || []).filter(x => x != null);
    if (cl.length >= 10) { hi = Math.max(...cl, q.px); lo = Math.min(...cl, q.px); } } catch (e) {}
  return {px: q.px, pv: q.pv, hi, lo};
}
function fxTxt(f){
  if (!f || !f.px) return "";
  const d = f.pv ? f.px - f.pv : 0, p = f.pv ? d / f.pv * 100 : 0, a = Math.abs(d);
  const mv = a < 0.005 ? "持平" : `台幣${d > 0 ? "貶" : "升"} ${a >= 0.1 ? (a * 10).toFixed(1) + " 角" : Math.round(a * 100) + " 分"}`;
  let pos = "";
  if (f.hi != null && f.hi - f.lo >= 0.05) { const r = (f.px - f.lo) / (f.hi - f.lo);
    pos = r >= 0.9 ? "，台幣在近一個月最弱的位置" : r <= 0.1 ? "，台幣在近一個月最強的位置" : ""; }
  const say = p >= 0.3 ? "台幣明顯貶值，常是外資把錢匯出、賣台股，對台股偏空（出口電子股帳上有匯兌收益）"
    : p <= -0.3 ? "台幣明顯升值，常是外資匯入買台股，對台股偏多（出口商的匯兌收益會變少）"
    : p >= 0.1 ? "台幣小貶，外資略偏匯出，影響有限"
    : p <= -0.1 ? "台幣小升，外資略偏匯入，影響有限"
    : "匯率平穩，外資資金進出不大";
  return `💱 美元兌台幣 ${f.px.toFixed(3)}（${mv}${a >= 0.005 ? `，${p > 0 ? "+" : ""}${p.toFixed(2)}%` : ""}${pos}）→ ${say}。`;
}

/* 各時間點的摘要內容:回傳 null 代表資料還沒好(下一分鐘再試) */
async function genAm(T){
  const y = await spark(["^GSPC", "^IXIC", "^SOX", "TSM", "^VIX"]), g = k => y[k] || {}; if (!g("^GSPC").px) return null;
  const fx = fxTxt(await fxTwd());
  return {title: `☀️ 巴菲遠晨報 ${md(T.day)}`, body: `美股：標普 ${pc(g("^GSPC").chg, 2)}、那斯達克 ${pc(g("^IXIC").chg, 2)}、費半 ${pc(g("^SOX").chg, 2)}；台積電 ADR ${pc(g("TSM").chg, 2)}；VIX ${g("^VIX").px ? g("^VIX").px.toFixed(1) : "—"}。${fx ? fx + " " : ""}台股 09:00 開盤。`};
}
async function genTw(T, k){
  const q = await mis(["tse_t00.tw", "otc_o00.tw", "tse_2330.tw"]), t = q.t00, o = q.o00, s = q["2330"];
  if (!t || t.d != T.day.replace(/-/g, "") || (t.t || "") < (k == "open" ? "09:00" : "13:30")) return null;
  const ox = o ? `；櫃買 ${nf(o.px, 2)}（${pc(chg(o), 2)}）` : "", sx = s ? `；台積電 ${nf(s.px)}（${pc(chg(s), 2)}）` : "";
  if (k == "open") return {title: `🔔 台股開盤 ${md(T.day)}`, body: `加權開 ${nf(t.o)}（${pc(t.o && (t.o / t.y - 1) * 100, 2)}），現 ${nf(t.px)}（${pc(chg(t), 2)}）${ox}${sx}。`, radar: 1};
  return {title: `🔔 台股收盤 ${md(T.day)}`, body: `加權收 ${nf(t.px, 2)}，${t.px >= t.y ? "漲" : "跌"} ${nf(Math.abs(t.px - t.y), 2)} 點（${pc(chg(t), 2)}）${ox}${sx}。`, radar: 1};
}
async function futOI(day){   // 期交所 臺股期貨 外資淨未平倉(口);CSV 是 Big5,只取數字欄,用每天第 3 列(自營商、投信、外資及陸資)
  const s = day.replace(/-/g, "/"), f = new Date(Date.parse(day) - 12 * 864e5).toISOString().slice(0, 10).replace(/-/g, "/");
  const b = await getJ("https://www.taifex.com.tw/cht/3/futContractsDateDown", {method: "POST", raw: 1, headers: {"Content-Type": "application/x-www-form-urlencoded"}, body: `queryStartDate=${encodeURIComponent(f)}&queryEndDate=${encodeURIComponent(s)}&commodityId=TXF`});
  if (!b) return null; let txt = ""; for (let i = 0; i < b.length; i++) txt += String.fromCharCode(b[i]);
  const G = {}; for (const ln of txt.split(/\r?\n/)) { const c = ln.split(","); if (/^\d{4}\/\d{2}\/\d{2}$/.test(c[0]) && c.length >= 15) (G[c[0]] = G[c[0]] || []).push(+c[13]); }
  const ds = Object.keys(G).filter(d => G[d].length == 3).sort(); if (!ds.length || ds[ds.length - 1] != s) return null;
  return {oi: G[s][2], prev: ds.length > 1 ? G[ds[ds.length - 2]][2] : null};
}
async function genInst(T){
  const d = T.day.replace(/-/g, ""), roc = `${+d.slice(0, 4) - 1911}/${d.slice(4, 6)}/${d.slice(6)}`;
  const j = await getJ(`https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate=${d}&type=day&response=json`);
  if (!j || j.stat != "OK" || j.date != d) return null;
  const a = {fi: 0, it: 0, dl: 0, tot: 0}; for (const r of j.data) { const v = num(r[3]) / 1e8; if (r[0].startsWith("外資")) a.fi += v; else if (r[0].startsWith("投信")) a.it += v; else if (r[0].startsWith("自營商")) a.dl += v; else if (r[0].startsWith("合計")) a.tot = v; }
  let b = null; const tp = await getJ(`https://www.tpex.org.tw/www/zh-tw/insti/summary?type=Daily&date=${d.slice(0, 4)}/${d.slice(4, 6)}/${d.slice(6)}&response=json`), tb = tp && tp.tables && tp.tables[0];
  if (tb && tb.data && (!tb.date || tb.date == roc)) { b = {}; for (const r of tb.data) { const n = String(r[0]).trim(), v = num(r[3]) / 1e8; if (n == "外資及陸資合計") b.fi = v; else if (n == "投信") b.it = v; else if (n == "自營商合計") b.dl = v; else if (n.startsWith("三大法人合計")) b.tot = v; } if (b.tot == null) b = null; }
  const fut = await futOI(T.day);
  if (!fut && T.m < 930) return null;   // 15:30 前等期交所期貨資料;櫃買中心擋雲端主機(302),上櫃抓得到才附上
  const mt = await getJ(`https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=${d}&response=json`), mr = mt && mt.data && mt.data.find(r => r[0] == roc), amt = mr ? num(mr[2]) / 1e8 : null;
  let body = `上市：外資 ${yi(a.fi)} 億、投信 ${yi(a.it)} 億、自營商 ${yi(a.dl)} 億，合計 ${yi(a.tot)} 億${amt ? `（大盤成交 ${nf(amt)} 億）` : ""}。`;
  if (b) body += `上櫃：外資 ${yi(b.fi)}、投信 ${yi(b.it)}、自營商 ${yi(b.dl)}，合計 ${yi(b.tot)} 億。`;
  if (fut) { const A = Math.abs(fut.oi), pA = fut.prev == null ? null : Math.abs(fut.prev), same = fut.prev != null && (fut.prev < 0) == (fut.oi < 0);
    body += `外資台指期${fut.oi < 0 ? "淨空單" : "淨多單"} ${nf(A)} 口${same && A != pA ? `（比前一日${A > pA ? "多" : "少"} ${nf(Math.abs(A - pA))} 口）` : ""}。`; }
  body += `→ 法人今天${a.tot + (b ? b.tot : 0) >= 0 ? "偏買" : "偏賣"}。${b ? "" : "（上櫃法人稍晚見網站法人儀表板）"}`;
  return {title: `🏦 三大法人 ${md(T.day)}`, body};
}
async function genUs(N, k){
  const y = await spark(["^DJI", "^GSPC", "^IXIC", "^SOX", "TSM", "^VIX"]), g = x => y[x] || {}, sp = g("^GSPC");
  if (!sp.px || sp.day != N.day || (k == "uso" && sp.hm < "09:30")) return null;
  let body = `道瓊 ${nf(g("^DJI").px)}（${pc(g("^DJI").chg, 2)}）、標普 ${nf(sp.px)}（${pc(sp.chg, 2)}）、那斯達克 ${nf(g("^IXIC").px)}（${pc(g("^IXIC").chg, 2)}）、費半 ${nf(g("^SOX").px)}（${pc(g("^SOX").chg, 2)}）；台積電 ADR ${nf(g("TSM").px, 2)}（${pc(g("TSM").chg, 2)}）`;
  if (k == "uso") return {title: `🇺🇸 美股開盤（美東 ${md(N.day)}）`, body: body + "。"};
  const v = g("^VIX").px, s = [g("^SOX").chg, g("TSM").chg].filter(x => x != null), av = s.length ? s.reduce((a, b) => a + b, 0) / s.length : 0;
  const fx = fxTxt(await fxTwd());
  return {title: `🇺🇸 美股收盤（美東 ${md(N.day)}）`, body: body + `${v ? `；VIX ${v.toFixed(1)}` : ""}。${fx ? fx + " " : ""}→ 台股今天開盤參考：${av >= 1 ? "偏多" : av <= -1 ? "偏空" : "持平"}（看費半與台積電 ADR，僅供參考）。`};
}

/* ---------- ⚡ 總經快訊 ----------
 * 美國:美東週一～五 08:25～11:40 每 5 分鐘看 FRED(勞工統計局/商務部數據 08:30、密大信心 10:00 公布後幾分鐘內 FRED 就更新)
 * FOMC:美東 14:00～15:30 每 3 分鐘看聯準會新聞稿 RSS;台灣:每 30 分鐘看網站 data/macro.json(GitHub Actions 每天 15:40/21:30/22:30 更新)
 * 第一次看到某指標只記錄、不發(避免舊數字被當快訊);只跟「前一次公布值」比,沒有市場預期值 */
const MACR = [
  {k: "CPI", n: "🇺🇸 CPI 消費者物價", s: ["CPIAUCSL", "CPILFESL"], f: "m"},
  {k: "PCE", n: "🇺🇸 PCE 物價（聯準會最看重）", s: ["PCEPILFE", "PCEPI"], f: "m"},
  {k: "PPI", n: "🇺🇸 PPI 生產者物價", s: ["PPIFIS"], f: "m"},
  {k: "NFP", n: "🇺🇸 非農就業＋失業率", s: ["PAYEMS", "UNRATE"], f: "m"},
  {k: "RET", n: "🇺🇸 零售銷售", s: ["RSAFS"], f: "m"},
  {k: "GDP", n: "🇺🇸 GDP 經濟成長率", s: ["A191RL1Q225SBEA"], f: "q"},
  {k: "CLM", n: "🇺🇸 初領失業救濟金", s: ["ICSA"], f: "w"},
  // 密大消費者信心不列:FRED 應密大要求延後 1 個月才放數字,不是快訊
  {k: "PHI", n: "🇺🇸 費城聯準會製造業指數", s: ["GACDFSA066MSFRBPHI"], f: "m"},
];
const MAC_GAP = {m: 20, w: 5, q: 25};          // 抓到新數字後幾天內不用再看(月資料 20 天、週資料 5 天、季資料 25 天)
const f2 = (x, d = 2) => x == null || !isFinite(x) ? "—" : x.toFixed(d);
const sg2 = (x, d = 2) => x == null || !isFinite(x) ? "—" : (x > 0 ? "+" : "") + x.toFixed(d);
const ymTxt = d => `${+d.slice(5, 7)} 月`;
async function fred(id, months){
  const st = new Date(Date.now() - months * 31 * 864e5).toISOString().slice(0, 10);
  const r = await fetch(`https://fred.stlouisfed.org/graph/fredgraph.csv?id=${id}&cosd=${st}`, {cf: {cacheTtl: 0}});
  if (!r.ok) throw new Error("FRED " + id + " " + r.status);
  const rows = (await r.text()).split(/\r?\n/).slice(1).map(l => l.split(",")).filter(c => c.length == 2 && /^\d{4}-\d\d-\d\d$/.test(c[0]) && c[1] !== "" && c[1] !== ".").map(c => [c[0], +c[1]]);
  if (!rows.length) throw new Error("FRED " + id + " 空");
  return rows;
}
const yoyAt = (R, i) => {                     // 年增率;去年同月官方沒資料(例:2025 年 10 月美國政府停擺)時,用前後月份幾何平均推估
  const d = R[i][0], y = +d.slice(0, 4), m = +d.slice(5, 7), g = (yy, mm) => { while (mm < 1) { mm += 12; yy--; } while (mm > 12) { mm -= 12; yy++; } const r = R.find(x => x[0] == `${yy}-${String(mm).padStart(2, "0")}-01`); return r ? r[1] : null; };
  let p = g(y - 1, m); if (p == null) { const a = g(y - 1, m - 1), b = g(y - 1, m + 1); if (a && b) p = Math.sqrt(a * b); }
  return p ? (R[i][1] / p - 1) * 100 : null; };
const momAt = (R, i) => i > 0 ? (R[i][1] / R[i - 1][1] - 1) * 100 : null;
const EFF = {
  hot: "降息機會變小，美債殖利率容易上升，科技股、成長股壓力較大；台股電子權值股隔天開盤容易跟著修正。",
  cool: "降息預期升溫，資金比較願意回到股市，科技股、成長股通常受惠；台股電子股隔天開盤有機會偏強。",
};
/* 各指標的白話判讀:回傳 {head(標題用), num(數字), read(判讀), eff(對股市), dir(偏多/偏空/中性)} */
function macEval(R, D){
  const L = a => a.length - 1;
  if (R.k == "CPI" || R.k == "PCE") {
    const [A, B] = D, a1 = yoyAt(A, L(A)), a0 = yoyAt(A, L(A) - 1), b1 = yoyAt(B, L(B)), b0 = yoyAt(B, L(B) - 1), mm = momAt(A, L(A));
    const core = R.k == "CPI" ? {n: "核心 CPI", v: b1, p: b0} : {n: "核心 PCE", v: a1, p: a0}, head = R.k == "CPI" ? {n: "CPI", v: a1, p: a0} : {n: "PCE", v: b1, p: b0};
    if ([head.v, head.p, core.v, core.p].some(x => x == null || !isFinite(x))) return null;
    const dc = core.v - core.p, dh = head.v - head.p, up = dc >= 0.1 || (dh >= 0.15 && dc >= 0), dn = dc <= -0.1 || (dh <= -0.15 && dc <= 0);
    const hi = core.v >= 3 ? "仍明顯高於聯準會 2% 目標" : core.v >= 2.5 ? "還高於聯準會 2% 目標" : "已接近聯準會 2% 目標";
    return {head: `${head.n} 年增 ${f2(head.v)}%（前值 ${f2(head.p)}%）`,
      num: `${head.n} 年增 ${f2(head.v)}%（前值 ${f2(head.p)}%）${R.k == "CPI" ? `、月增 ${sg2(mm)}%` : ""}；${core.n} 年增 ${f2(core.v)}%（前值 ${f2(core.p)}%）`,
      read: up ? `通膨比上一次熱（${core.n}升 ${f2(dc)} 個百分點），${hi}。` : dn ? `通膨比上一次降溫（${core.n}降 ${f2(-dc)} 個百分點），${hi}。` : `通膨和上一次差不多，${hi}。`,
      eff: up ? EFF.hot : dn ? EFF.cool : core.v >= 3 ? "通膨卡在高檔，降息不會太快，股市沒有新的利多，波動看其他數據。" : "對股市影響不大，市場會轉看下一個數據與聯準會官員的說法。",
      dir: up ? "偏空" : dn ? "偏多" : "中性"};
  }
  if (R.k == "PPI") {
    const [A] = D, v = yoyAt(A, L(A)), p = yoyAt(A, L(A) - 1); if (v == null || p == null) return null; const d = v - p, up = d >= 0.2, dn = d <= -0.2;
    return {head: `PPI 年增 ${f2(v)}%（前值 ${f2(p)}%）`, num: `PPI 年增 ${f2(v)}%（前值 ${f2(p)}%）、月增 ${sg2(momAt(A, L(A)))}%`,
      read: up ? "工廠端成本升溫，之後可能慢慢轉嫁到 CPI。" : dn ? "工廠端成本降溫，對之後的 CPI 是好消息。" : "工廠端成本變化不大。",
      eff: (up ? "對股市略偏空：市場擔心通膨回頭、降息延後。" : dn ? "對股市略偏多：通膨壓力減輕。" : "對股市影響有限。") + "PPI 是 CPI 的前哨，影響通常比 CPI 小。", dir: up ? "偏空" : dn ? "偏多" : "中性"};
  }
  if (R.k == "NFP") {
    const [A, U] = D, n = L(A), c = A[n][1] - A[n - 1][1], cp = A[n - 1][1] - A[n - 2][1], u = U[L(U)][1], up = U[L(U) - 1][1], du = u - up, w = x => `${sg2(x / 10, 1)} 萬人`;
    const t = c >= 250 ? ["就業過熱", "就業太強，市場怕聯準會不急著降息，美債殖利率容易上升，科技股、成長股壓力較大。", "偏空"]
      : c >= 100 ? ["溫和成長", "最理想的「不冷不熱」：景氣穩、通膨壓力不大，對股市偏多。", "偏多"]
      : c >= 0 ? ["明顯放緩", "降息機會增加（利多），但也要留意景氣轉弱；股市常先漲、之後看企業獲利。", "中性"]
      : ["就業減少", "就業負成長是衰退警訊，市場會擔心企業獲利，股市容易下跌、資金轉向債券。", "偏空"];
    return {head: `非農新增 ${w(c)}（前值 ${w(cp)}）、失業率 ${f2(u, 1)}%`, num: `非農就業新增 ${w(c)}（前值 ${w(cp)}）；失業率 ${f2(u, 1)}%（前值 ${f2(up, 1)}%）`,
      read: `${t[0]}。${du >= 0.2 ? `失業率跳升 ${f2(du, 1)} 個百分點，市場會擔心景氣衰退。` : du <= -0.2 ? "失業率明顯下降，就業市場偏緊。" : "失業率變化不大。"}`,
      eff: t[1] + "非農常讓美股單日大漲大跌，台股隔天開盤跟著反應。", dir: du >= 0.2 && t[2] != "偏空" ? "中性" : t[2]};
  }
  if (R.k == "RET") {
    const [A] = D, m = momAt(A, L(A)), mp = momAt(A, L(A) - 1), y = yoyAt(A, L(A));
    return {head: `零售銷售月增 ${sg2(m)}%（前值 ${sg2(mp)}%）`, num: `零售銷售月增 ${sg2(m)}%（前值 ${sg2(mp)}%）、年增 ${sg2(y)}%`,
      read: m >= 0.6 ? "美國人花錢力道強。" : m >= 0 ? "消費穩健。" : "消費轉弱，美國人開始省錢。",
      eff: m >= 0.6 ? "景氣強對企業獲利是好事，但太強會讓降息延後，股市偏多但波動加大。" : m >= 0 ? "對股市偏多：景氣穩、通膨壓力不大。" : "對股市偏空：消費占美國經濟七成，轉弱會讓市場擔心景氣。", dir: m >= 0.6 ? "中性" : m >= 0 ? "偏多" : "偏空"};
  }
  if (R.k == "GDP") {
    const [A] = D, v = A[L(A)][1], p = A[L(A) - 1][1], q = A[L(A)][0], qn = `${q.slice(0, 4)} 第 ${Math.floor((+q.slice(5, 7) - 1) / 3) + 1} 季`;
    const t = v >= 3 ? ["經濟強勁", "企業獲利有支撐，但太熱會讓降息延後。", "中性"] : v >= 1 ? ["溫和成長", "最理想的速度，對股市偏多。", "偏多"] : v >= 0 ? ["成長放緩", "市場會開始擔心景氣，但也提高降息機會。", "中性"] : ["負成長", "衰退警訊，股市容易下跌。", "偏空"];
    return {head: `GDP ${qn}年化 ${sg2(v, 1)}%（前值 ${sg2(p, 1)}%）`, num: `${qn} GDP 年化季增 ${sg2(v, 1)}%（前一季 ${sg2(p, 1)}%）`, read: t[0] + "。", eff: t[1], dir: t[2]};
  }
  if (R.k == "CLM") {
    const [A] = D, v = A[L(A)][1], p = A[L(A) - 1][1], w = x => `${(x / 1e4).toFixed(1)} 萬人`;
    const t = v >= 260000 ? ["裁員升溫", "就業市場轉弱，市場會擔心景氣，股市偏空（但也提高降息機會）。", "偏空"] : v >= 230000 ? ["略為增加，要留意", "還在可接受範圍，影響有限。", "中性"] : ["就業市場穩", "裁員不多，景氣還穩。", "中性"];
    return {head: `初領失業金 ${w(v)}（前值 ${w(p)}）`, num: `初領失業救濟金 ${w(v)}（前一週 ${w(p)}）`, read: t[0] + "。", eff: t[1] + "這是每週數據，單週影響通常不大。", dir: t[2]};
  }
  if (R.k == "UMS" || R.k == "PHI") {
    const [A] = D, v = A[L(A)][1], p = A[L(A) - 1][1], d = v - p, nm = R.k == "UMS" ? "密大消費者信心" : "費城聯準會製造業指數";
    const read = R.k == "UMS" ? (d >= 2 ? "美國人對未來比較有信心。" : d <= -2 ? "美國人對未來比較悲觀。" : "信心變化不大。") + (v < 60 ? "整體信心仍偏低。" : "")
      : (v > 0 ? "工廠景氣在擴張（大於 0）。" : "工廠景氣在收縮（小於 0）。") + (d >= 5 ? "比上個月明顯變好。" : d <= -5 ? "比上個月明顯變差。" : "");
    return {head: `${nm} ${f2(v, 1)}（前值 ${f2(p, 1)}）`, num: `${nm} ${f2(v, 1)}（前值 ${f2(p, 1)}）`, read,
      eff: (d >= (R.k == "UMS" ? 2 : 5) ? "對股市略偏多。" : d <= -(R.k == "UMS" ? 2 : 5) ? "對股市略偏空。" : "對股市影響有限。") + "這類調查數據影響通常一兩天。",
      dir: d >= (R.k == "UMS" ? 2 : 5) ? "偏多" : d <= -(R.k == "UMS" ? 2 : 5) ? "偏空" : "中性"};
  }
  return null;
}
async function macGet(env, k){ const r = await env.DB.prepare("SELECT v FROM state WHERE k=?").bind("mac:" + k).first(); return r ? JSON.parse(r.v) : null; }
async function macPut(env, k, v){ await env.DB.prepare("INSERT OR REPLACE INTO state(k,v,ts) VALUES(?,?,?)").bind("mac:" + k, JSON.stringify(v), Date.now()).run(); }
async function macBuild(R){
  const mo = R.f == "q" ? 30 : R.f == "w" ? 3 : 26, D = [];
  for (const id of R.s) D.push(await fred(id, mo));
  const E = macEval(R, D); if (!E) return null;
  const d = D[0][D[0].length - 1][0];
  return {k: `${R.k}:${d}`, g: "US", obs: d, title: `⚡ ${R.n}｜${E.head}`, body: `📊 ${E.num}。\n🔍 判讀：${E.read}\n📈 對股市：${E.dir}——${E.eff}\n（和前一次公布值比較；市場預期值請以財經新聞為準）`, dir: E.dir, short: `${E.dir}｜${E.read}`};
}
async function macUS(env){
  const out = [];
  for (const R of MACR) {
    try {
      const st = await macGet(env, R.k);
      if (st && st.seen && Date.now() - st.seen < MAC_GAP[R.f] * 864e5) continue;
      const A = await fred(R.s[0], R.f == "q" ? 30 : R.f == "w" ? 3 : 26), d = A[A.length - 1][0];
      if (!st) { await macPut(env, R.k, {d, seen: 0}); out.push([R.k, "基準", d]); continue; }       // 第一次:只記錄
      if (d <= st.d) continue;
      const M = await macBuild(R); if (!M) continue;
      await macPut(env, R.k, {d, seen: Date.now()}); out.push([R.k, await macDeliver(env, M)]);
    } catch (e) { out.push([R.k, "錯誤 " + e.message]); }
  }
  return out;
}
/* FOMC:聯準會新聞稿 RSS 出現新的「FOMC statement」→ 讀聲明裡的利率區間 */
const fedNum = t => { const m = String(t).trim().match(/^(\d+)(?:-(\d+)\/(\d+))?$/); return m ? +m[1] + (m[2] ? +m[2] / +m[3] : 0) : null; };
async function macFOMC(env){
  const x = await (await fetch("https://www.federalreserve.gov/feeds/press_monetary.xml", {headers: UA})).text();
  const it = [...x.matchAll(/<item>([\s\S]*?)<\/item>/g)].map(m => ({t: (m[1].match(/<title>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?<\/title>/) || [])[1] || "", u: ((m[1].match(/<link>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?<\/link>/) || [])[1] || "").trim()})).find(i => /FOMC statement/i.test(i.t));
  if (!it || !it.u) return "沒有聲明";
  const st = await macGet(env, "FOMC");
  if (st && st.u == it.u) return "沒有新聲明";
  const h = await (await fetch(it.u, {headers: UA})).text(), m = h.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").match(/target range for the federal funds rate (?:at|to) ([\d\-\/]+) to ([\d\-\/]+) percent/i);
  if (!m) return "讀不到利率";
  const lo = fedNum(m[1]), up = fedNum(m[2]);
  if (!st) { await macPut(env, "FOMC", {u: it.u, up}); return "基準 " + up; }
  const bp = Math.round((up - st.up) * 100), day = new Date(Date.now() - 5 * 3600e3).toISOString().slice(0, 10);
  const t = bp > 0 ? ["升息 " + bp / 25 + " 碼", "升息讓借錢變貴，股市（尤其科技股、成長股）偏空；美元走強，台幣容易貶值、外資可能賣台股。", "偏空"]
    : bp < 0 ? ["降息 " + -bp / 25 + " 碼", "降息讓資金變便宜，股市偏多；但如果是因為景氣變差才急降，要留意後續企業獲利。", "偏多"]
    : ["利率不變", "市場會看聲明和主席記者會的口氣：暗示之後會降息 → 偏多；暗示不降或可能升息 → 偏空。", "中性"];
  const M = {k: `FOMC:${day}`, g: "US", obs: day, title: `⚡ 🇺🇸 FOMC 利率決策｜${t[0]}，利率區間 ${f2(lo)}%～${f2(up)}%`,
    body: `📊 聯準會${t[0]}，聯邦基金利率目標區間 ${f2(lo)}%～${f2(up)}%（之前上限 ${f2(st.up)}%）。\n🔍 判讀：${t[0] == "利率不變" ? "這次按兵不動。" : "利率方向改變，是全球股市最重要的消息。"}\n📈 對股市：${t[2]}——${t[1]}台股隔天開盤會直接反應。`, dir: t[2], short: `${t[2]}｜${t[0]}`};
  await macPut(env, "FOMC", {u: it.u, up});
  return await macDeliver(env, M);
}
/* 台灣:網站 data/macro.json 的景氣燈號/出口/外銷訂單有新月份 */
async function macTW(env){
  const r = await fetch("https://yuan780903-cpu.github.io/tw-etf-dividend/data/macro.json?" + Date.now(), {cf: {cacheTtl: 0}}); if (!r.ok) return "macro.json " + r.status;
  const tw = (await r.json()).tw || {}, out = [];
  const LCOL = v => v >= 38 ? "紅燈" : v >= 32 ? "黃紅燈" : v >= 23 ? "綠燈" : v >= 17 ? "黃藍燈" : "藍燈";
  for (const k of ["LIGHT", "EXPORT", "ORDERS"]) {
    const R = (tw[k] || {}).rows || []; if (R.length < 2) continue;
    const [d, v] = R[R.length - 1], p = R[R.length - 2][1], st = await macGet(env, "TW" + k);
    if (!st) { await macPut(env, "TW" + k, {d}); out.push([k, "基準", d]); continue; }
    if (d <= st.d) continue;
    let M;
    if (k == "LIGHT") { const c = LCOL(v), cp = LCOL(p);
      const t = c == "紅燈" ? ["景氣過熱", "紅燈代表景氣熱到最高檔，歷史上常是股市高檔區，追高要小心、留意轉弱。", "中性"] : c == "黃紅燈" ? ["景氣熱絡", "景氣好、企業獲利佳，對股市偏多。", "偏多"]
        : c == "綠燈" ? ["景氣穩定", "景氣穩定成長，對股市中性偏多。", "偏多"] : c == "黃藍燈" ? ["景氣轉弱", "景氣轉弱，企業獲利可能下修，股市偏空。", "偏空"] : ["景氣低迷", "短期股市偏弱，但歷史上藍燈常是長線分批布局的時機。", "偏空"];
      M = {title: `⚡ 🇹🇼 景氣對策信號｜${ymTxt(d)}${c} ${v} 分（前值 ${cp} ${p} 分）`, num: `${ymTxt(d)}景氣對策信號 ${c}，綜合分數 ${v} 分（前一個月 ${cp} ${p} 分）`, read: `${t[0]}${v > p ? "，分數比上個月高" : v < p ? "，分數比上個月低" : ""}。`, eff: t[1], dir: t[2]}; }
    else { const nm = k == "EXPORT" ? "海關出口" : "外銷訂單", d0 = v - p;
      const t = v >= 10 ? ["高成長", `${nm}持續大幅成長，台灣企業（尤其電子業）獲利有支撐，對台股偏多。`, "偏多"] : v >= 0 ? ["溫和成長", "成長不快但還在增加，對台股中性偏多。", "中性"] : ["衰退", `${nm}年減，市場會擔心景氣與企業獲利，對台股偏空。`, "偏空"];
      M = {title: `⚡ 🇹🇼 ${nm}｜${ymTxt(d)}年增 ${sg2(v, 1)}%（前值 ${sg2(p, 1)}%）`, num: `${ymTxt(d)}${nm}年增 ${sg2(v, 1)}%（前一個月 ${sg2(p, 1)}%）`,
        read: `${t[0]}${d0 >= 5 ? "，成長比上個月加快" : d0 <= -5 ? "，成長比上個月放緩" : ""}。${k == "ORDERS" ? "外銷訂單是未來 1～3 個月出口的領先指標。" : ""}`, eff: t[1], dir: t[2]}; }
    const Mx = {k: `TW${k}:${d}`, g: "TW", obs: d, title: M.title, body: `📊 ${M.num}。\n🔍 判讀：${M.read}\n📈 對股市：${M.dir}——${M.eff}\n（台灣數據由網站每天更新時取得，可能比官方公布晚幾小時）`, dir: M.dir, short: `${M.dir}｜${M.read}`};
    await macPut(env, "TW" + k, {d}); out.push([k, await macDeliver(env, Mx)]);
  }
  return out;
}
async function macDeliver(env, M){
  const DB = env.DB, now = Date.now();
  const ins = await DB.prepare("INSERT OR IGNORE INTO macro(k,ts,g,title,body,dir) VALUES(?,?,?,?,?,?)").bind(M.k, now, M.g, M.title, M.body, M.dir).run();
  if (!ins.meta.changes) return 0;
  const subs = ((await DB.prepare("SELECT * FROM subs WHERE rd != 0").all()).results || []).filter(s => { const c = JSON.parse(s.cfg || "{}"); return "b_mac" in c ? !!c.b_mac : c.brief !== false; });
  if (!subs.length) return 0;
  await DB.batch(subs.map(s => DB.prepare("INSERT INTO alerts(sub,ts,code,title,body,bad) VALUES(?,?,?,?,?,0)").bind(s.id, now, "MAC", M.title.replace(/^⚡\s*/, "⚡ "), M.short)));
  for (const s of subs) await push(env, s);
  return subs.length;
}
async function macRun(env, T){
  const N = nyNow(), out = {};
  if (N.wd >= 1 && N.wd <= 5 && N.m >= 505 && N.m <= 700 && N.m % 5 == 0) { try { out.us = await macUS(env); } catch (e) { out.usErr = e.message; } }
  if (N.wd >= 1 && N.wd <= 5 && N.m >= 840 && N.m <= 930 && N.m % 3 == 0) { try { out.fomc = await macFOMC(env); } catch (e) { out.fomcErr = e.message; } }
  if (T.m % 30 == 7) { try { out.tw = await macTW(env); } catch (e) { out.twErr = e.message; } }
  return out;
}

/* 存進全站時間軸,再推播給有訂閱且開著這種摘要的人 */
async function deliver(env, k, day, B){
  const DB = env.DB, now = Date.now();
  const ins = await DB.prepare("INSERT OR IGNORE INTO briefs(day,k,ts,title,body) VALUES(?,?,?,?,?)").bind(day, k, now, B.title, B.body).run();
  if (!ins.meta.changes) return 0;
  const subs = ((await DB.prepare("SELECT * FROM subs WHERE rd != 0").all()).results || []).filter(s => { const c = JSON.parse(s.cfg || "{}"); return BKEY[k] in c ? !!c[BKEY[k]] : c.brief !== false; });
  if (!subs.length) return 0;
  let Q = {}; if (B.radar) { const codes = [...new Set(subs.flatMap(s => JSON.parse(s.codes || "[]")))].slice(0, 120); if (codes.length) Q = await mis(codes.flatMap(c => [`tse_${c}.tw`, `otc_${c}.tw`])); }
  const cnt = {}; if (k == "close") for (const r of ((await DB.prepare("SELECT sub, COUNT(*) n FROM alerts WHERE ts>? AND code NOT IN ('BRIEF','TEST') GROUP BY sub").bind(now - 6 * 3600e3).all()).results || [])) cnt[r.sub] = r.n;
  const F = x => `${x[2] || x[0]} ${pc(x[1])}`, rows = [];
  for (const s of subs) {
    let body = B.body; const mine = JSON.parse(s.codes || "[]");
    if (B.radar) { const L = mine.map(c => Q[c] ? [c, chg(Q[c]), Q[c].nm] : null).filter(Boolean).sort((a, b) => b[1] - a[1]);
      if (L.length) body += ` 你的雷達：${L.length > 3 ? `最強 ${L.slice(0, 2).map(F).join("、")}；最弱 ${L.slice(-2).reverse().map(F).join("、")}` : L.map(F).join("、")}。`; }
    if (k == "close" && cnt[s.id]) body += ` 今天共 ${cnt[s.id]} 則盤中警示。`;
    if (k == "am" && mine.length) body += ` 雷達監控中 ${mine.length} 檔。`;
    rows.push(DB.prepare("INSERT INTO alerts(sub,ts,code,title,body,bad) VALUES(?,?,?,?,?,0)").bind(s.id, now, "BRIEF", B.title, body));
  }
  await DB.batch(rows);
  for (const s of subs) await push(env, s);
  return subs.length;
}
async function briefs(env, T){
  const N = nyNow(), out = []; let hol = null;
  for (const [k, zone, a, b, step] of SLOTS) {
    const Z = zone == "tw" ? T : N; if (Z.wd < 1 || Z.wd > 5 || Z.m < a || Z.m > b || (Z.m - a) % step) continue;
    if (zone == "tw") { if (hol == null) hol = await twHoliday(env, T.day); if (hol) continue; }
    if (await env.DB.prepare("SELECT 1 FROM briefs WHERE day=? AND k=?").bind(Z.day, k).first()) continue;
    const B = k == "am" ? await genAm(T) : k == "inst" ? await genInst(T) : zone == "tw" ? await genTw(T, k) : await genUs(N, k);
    if (B) out.push([k, await deliver(env, k, Z.day, B)]);
  }
  return out;
}

/* ---------- 💰 配息提醒(網站「我的配息試算」持股):台北 08:01～08:29 每分鐘檢查一批訂閱者,有新事件就推播 ----------
   事件表 data/pf_events.json 由 GitHub Actions 每天產生(scripts/build_pf_events.py);同一件事只推一次(pffired)。
   網站每次打開會同步持股到 /pfsub,同時把「現在已經看得到的事件」記成已通知,避免網站剛跳過、隔天早上又推一次。 */
const PFE = "https://yuan780903-cpu.github.io/tw-etf-dividend/data/pf_events.json";
const PF_BATCH = 15;
let PFC = null;
async function pfData(){
  if (PFC && Date.now() - PFC.t < 300e3) return PFC.d;
  const r = await fetch(PFE + "?t=" + Math.floor(Date.now() / 300e3), {cf: {cacheTtl: 120}});
  if (!r.ok) return PFC ? PFC.d : null;
  const d = await r.json(); PFC = {t: Date.now(), d}; return d;
}
const cleanPf = a => { const o = [], seen = new Set();
  for (const x of (Array.isArray(a) ? a : [])) { const id = String((x && x.id) || "").toUpperCase(), lots = +(x && x.lots);
    if (/^[0-9A-Z]{4,6}$/.test(id) && lots > 0 && lots < 1e6 && !seen.has(id)) { seen.add(id); o.push({id, lots: Math.round(lots * 1000) / 1000}); } }
  return o.slice(0, 60); };
const mdw = s => { const d = new Date(s + "T00:00:00Z"); return `${d.getUTCMonth() + 1}/${d.getUTCDate()}（${"日一二三四五六"[d.getUTCDay()]}）`; };
const cash$ = v => "$" + nf(Math.round(v));
const dayDiff = (a, b) => Math.round((Date.parse(a) - Date.parse(b)) / 864e5);
function pfEvents(E, pf, day){
  const out = [];
  for (const {id, lots} of pf) {
    const e = E[id]; if (!e) continue;
    const nm = `${id} ${e.n}`, sh = lots * 1000, L = +lots.toFixed(3);
    for (const [ex, cash, lb] of e.ex || []) {
      const n = dayDiff(ex, day); if (n < 0 || n > 30) continue;
      const amt = cash ? `每股 ${+cash} 元，你 ${L} 張約領 ${cash$(cash * sh)}` : "配息金額還沒公布";
      out.push({k: `exa:${id}:${ex}:${cash ? 1 : 0}`, title: `📅 ${nm} ${mdw(ex)} 除息`, body: `${amt}；最後買進日 ${mdw(lb)}，那天收盤前持有才領得到。`});
      if (lb == day) out.push({k: `exl:${id}:${ex}`, title: `⏰ 今天是 ${nm} 最後買進日`, body: `${mdw(ex)} 除息，今天收盤前持有才領得到這次配息。${cash ? `每股 ${+cash} 元，你 ${L} 張約領 ${cash$(cash * sh)}。` : ""}`});
    }
    for (const [pay, cash, ex] of e.pay || []) {
      const n = dayDiff(pay, day); if (n < 0 || n > 30 || !cash) continue;
      if (n == 0) out.push({k: `pyd:${id}:${pay}`, title: `💰 今天入帳：${nm} 約 ${cash$(cash * sh)}`, body: `每股 ${+cash} 元 × ${L} 張（${md(ex)} 除息）。單次股利/利息 2 萬元以上會扣二代健保，實際以券商入帳為準。`});
      else out.push({k: `pya:${id}:${pay}`, title: `💰 ${nm} ${mdw(pay)} 入帳約 ${cash$(cash * sh)}`, body: `已公告每股 ${+cash} 元 × ${L} 張（${md(ex)} 除息），再 ${n} 天入帳。`});
    }
    const f = e.fill;
    if (f && f[3] && f[4] - f[3] < 3) out.push({k: `fil:${id}:${f[0]}`, title: `✅ ${nm} 已填息`, body: `${mdw(f[0])} 除息（每股 ${+f[1]} 元），${f[5] ? mdw(f[5]) + " " : ""}第 ${f[3]} 個交易日收盤漲回除息前的 ${f[2]} 元。`});
  }
  return out;
}
async function pfMark(env, sid, ev){        // 記成已通知,回傳這次新出現的
  if (!ev.length) return [];
  const R = await env.DB.batch(ev.map(a => env.DB.prepare("INSERT OR IGNORE INTO pffired(sub,k,ts) VALUES(?,?,?)").bind(sid, a.k, Date.now())));
  return ev.filter((a, i) => R[i] && R[i].meta && R[i].meta.changes);
}
async function pfRun(env, T){
  if (T.m < 481 || T.m > 509) return null;
  const DB = env.DB, subs = (await DB.prepare("SELECT id, endpoint, pf FROM subs WHERE pf != '[]' AND (pfday IS NULL OR pfday < ?) LIMIT ?").bind(T.day, PF_BATCH).all()).results || [];
  if (!subs.length) return {checked: 0};
  const D = await pfData(); if (!D || !D.e) return {err: "沒有 pf_events"};
  let pushed = 0; const now = Date.now();
  for (const s of subs) {
    const neu = await pfMark(env, s.id, pfEvents(D.e, JSON.parse(s.pf || "[]"), T.day));
    const rows = [DB.prepare("UPDATE subs SET pfday=? WHERE id=?").bind(T.day, s.id)];
    if (neu.length > 3) rows.push(DB.prepare("INSERT INTO alerts(sub,ts,code,title,body,bad) VALUES(?,?,?,?,?,0)").bind(s.id, now, "PF", `🔔 ${neu.length} 則配息提醒`, neu.map(a => a.title.replace(/^\S+\s/, "")).join("\n")));
    else neu.forEach(a => rows.push(DB.prepare("INSERT INTO alerts(sub,ts,code,title,body,bad) VALUES(?,?,?,?,?,0)").bind(s.id, now, "PF", a.title, a.body)));
    await DB.batch(rows);
    if (neu.length) { await push(env, s); pushed++; }
  }
  return {checked: subs.length, pushed};
}

async function run(env){
  const T = tpe(), DB = env.DB, res = {};
  if (T.m == 480) { await DB.prepare("DELETE FROM alerts WHERE ts < ?").bind(Date.now() - 7 * 864e5).run(); await DB.prepare("DELETE FROM fired WHERE day < ?").bind(new Date(Date.now() - 3 * 864e5).toISOString().slice(0, 10)).run(); await DB.prepare("DELETE FROM briefs WHERE ts < ?").bind(Date.now() - 30 * 864e5).run(); await DB.prepare("DELETE FROM pffired WHERE ts < ?").bind(Date.now() - 150 * 864e5).run(); }
  try { const r = await pfRun(env, T); if (r) res.pf = r; } catch (e) { res.pfErr = e.message; }
  try { res.briefs = await briefs(env, T); } catch (e) { res.briefErr = e.message; }
  try { const m = await macRun(env, T); if (Object.keys(m).length) res.mac = m; } catch (e) { res.macErr = e.message; }
  if (!(T.wd >= 1 && T.wd <= 5) || T.m < 480 || T.m > 812) return res;          // 盤中雷達只在台北 08:00～13:32
  if (await twHoliday(env, T.day)) return {...res, skip: "台股休市"};
  const subs = (await DB.prepare("SELECT * FROM subs").all()).results || [];
  if (!subs.length) return {...res, subs: 0};
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
        await env.DB.prepare("INSERT INTO subs(id,endpoint,codes,cfg,refs,created,updated,fails) VALUES(?,?,?,?,?,?,?,0) ON CONFLICT(endpoint) DO UPDATE SET codes=excluded.codes,cfg=excluded.cfg,refs=excluded.refs,updated=excluded.updated,fails=0,rd=1")
          .bind(id, b.endpoint, JSON.stringify(cleanCodes(b.codes)), JSON.stringify(cfg), JSON.stringify(refs), now, now).run();
        return J(req, {ok: true, id, n: cleanCodes(b.codes).length});
      }
      if (p == "/unsub" && req.method == "POST") {    // 關盤中雷達;同一台還開著配息提醒就保留訂閱
        const b = await req.json(), s = await env.DB.prepare("SELECT id, pf FROM subs WHERE endpoint=?").bind(b.endpoint || "").first();
        if (s && s.pf && s.pf != "[]") await env.DB.prepare("UPDATE subs SET rd=0, codes='[]', refs='{}', cfg='{\"brief\":false}' WHERE id=?").bind(s.id).run();
        else await env.DB.prepare("DELETE FROM subs WHERE endpoint=?").bind(b.endpoint || "").run();
        return J(req, {ok: true});
      }
      if (p == "/pfsub" && req.method == "POST") {    // 配息提醒:同步持股(網站每次打開都會送),順便把現在看得到的事件記成已通知
        const b = await req.json(); if (!okEndpoint(b.endpoint)) return J(req, {error: "不支援的推播服務"}, 400);
        const pf = cleanPf(b.pf), now = Date.now(), ex = await env.DB.prepare("SELECT id FROM subs WHERE endpoint=?").bind(b.endpoint).first(), id = ex ? ex.id : crypto.randomUUID();
        await env.DB.prepare("INSERT INTO subs(id,endpoint,codes,cfg,refs,created,updated,fails,pf,rd) VALUES(?,?,'[]','{\"brief\":false}','{}',?,?,0,?,0) ON CONFLICT(endpoint) DO UPDATE SET pf=excluded.pf,updated=excluded.updated,fails=0")
          .bind(id, b.endpoint, now, now, JSON.stringify(pf)).run();
        let seen = 0; try { const D = await pfData(); if (D && D.e && b.seen !== false) seen = (await pfMark(env, id, pfEvents(D.e, pf, tpe().day))).length; } catch (e) {}
        return J(req, {ok: true, id, n: pf.length, seen});
      }
      if (p == "/pfunsub" && req.method == "POST") {  // 關配息提醒;同一台還開著盤中雷達就保留訂閱
        const b = await req.json(), s = await env.DB.prepare("SELECT id, rd FROM subs WHERE endpoint=?").bind(b.endpoint || "").first();
        if (s) { if (s.rd) await env.DB.prepare("UPDATE subs SET pf='[]', pfday=NULL WHERE id=?").bind(s.id).run(); else await env.DB.prepare("DELETE FROM subs WHERE id=?").bind(s.id).run(); }
        return J(req, {ok: true, rd: !!(s && s.rd)});
      }
      if (p == "/pftest" && req.method == "POST") {
        const b = await req.json(), s = await env.DB.prepare("SELECT * FROM subs WHERE endpoint=?").bind(b.endpoint || "").first(); if (!s) return J(req, {error: "尚未訂閱"}, 404);
        await env.DB.prepare("INSERT INTO alerts(sub,ts,code,title,body,bad) VALUES(?,?,?,?,?,0)").bind(s.id, Date.now(), "PF", "✅ 配息提醒推播測試成功", `關掉網站也會通知：持股 ${JSON.parse(s.pf || "[]").length} 檔的除息、最後買進日、入帳、填息（每天早上 8 點多檢查）`).run();
        return J(req, {ok: true, status: await push(env, s)});
      }
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
      if (p == "/briefs") {                        // 網站「今日盤勢摘要」時間軸(公開)
        const R = (await env.DB.prepare("SELECT day,k,ts,title,body FROM briefs WHERE ts>? ORDER BY ts DESC LIMIT 14").bind(Date.now() - 4 * 864e5).all()).results || [];
        return new Response(JSON.stringify({items: R, now: Date.now()}), {headers: {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "public, max-age=60", ...cors(req)}});
      }
      if (p == "/macro") {                         // 網站「⚡ 總經快訊」(公開):近 30 天最新 30 則
        const R = (await env.DB.prepare("SELECT k,ts,g,title,body,dir FROM macro WHERE ts>? ORDER BY ts DESC LIMIT 30").bind(Date.now() - 30 * 864e5).all()).results || [];
        return new Response(JSON.stringify({items: R, now: Date.now()}), {headers: {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "public, max-age=60", ...cors(req)}});
      }
      if (p == "/macprev") {                       // 測試用:用最新數字產生快訊文字(不存、不推播;每種 30 秒最多一次)
        const k = u.searchParams.get("k") || "", R = MACR.find(x => x.k == k), sk = "mp:" + k, row = await env.DB.prepare("SELECT v,ts FROM state WHERE k=?").bind(sk).first();
        if (!R) return J(req, {error: "k 要是 " + MACR.map(x => x.k).join("/")}, 400);
        if (row && Date.now() - row.ts < 30e3) return J(req, JSON.parse(row.v));
        const o = await macBuild(R); await env.DB.prepare("INSERT OR REPLACE INTO state(k,v,ts) VALUES(?,?,?)").bind(sk, JSON.stringify(o), Date.now()).run();
        return J(req, o);
      }
      if (p == "/preview") {                       // 測試用:產生摘要文字但不存、不推播(每種 30 秒最多一次)
        const k = u.searchParams.get("k") || "", T = tpe(), N = nyNow(), sk = "pv:" + k, row = await env.DB.prepare("SELECT v,ts FROM state WHERE k=?").bind(sk).first();
        if (!BKEY[k]) return J(req, {error: "k 要是 " + Object.keys(BKEY).join("/")}, 400);
        if (row && Date.now() - row.ts < 30e3) return J(req, JSON.parse(row.v));
        if (u.searchParams.get("hm")) { const [h, m] = u.searchParams.get("hm").split(":").map(Number); T.m = h * 60 + m; }
        const B = k == "am" ? await genAm(T) : k == "inst" ? await genInst(T) : ["open", "close"].includes(k) ? await genTw(T, k) : await genUs(N, k), o = {k, tw: T.day, ny: N.day + " " + Math.floor(N.m / 60) + ":" + String(N.m % 60).padStart(2, "0"), brief: B};
        await env.DB.prepare("INSERT OR REPLACE INTO state(k,v,ts) VALUES(?,?,?)").bind(sk, JSON.stringify(o), Date.now()).run();
        return J(req, o);
      }
      if (p == "/status") { const c = await env.DB.prepare("SELECT COUNT(*) n FROM subs").first(), t = await env.DB.prepare("SELECT ts FROM state ORDER BY ts DESC LIMIT 1").first(); return J(req, {subs: c.n, lastRun: t ? new Date(t.ts).toISOString() : null}); }
      return J(req, {name: "巴菲遠盤中雷達推播"});
    } catch (e) { return J(req, {error: e.message}, 500); }
  },
  async scheduled(ev, env, ctx){ ctx.waitUntil(run(env)); },
};
