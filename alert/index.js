/* 巴菲遠・盤中雷達雲端推播 Worker
 * - 網站把「雷達名單 + 警示條件 + 推播訂閱」存到這裡(POST /sub)
 * - 另有盤勢摘要(晨報/台股開盤/收盤/三大法人/美股開盤/美股收盤,見 SLOTS),存全站時間軸 /briefs 並推播
 * - Cron 盤中每分鐘抓證交所即時報價,依條件判斷,觸發就送 Web Push(網站關閉也收得到)
 * - 推播不帶內容(免加密),手機收到後由 Service Worker 呼叫 GET /pending 取得警示文字再跳通知
 * 秘密:VAPID_PRIVATE_JWK(wrangler secret)。公開金鑰放在 wrangler.toml 的 VAPID_PUBLIC。
 */
const ORIGINS = ["https://yuan780903-cpu.github.io", "http://localhost:8770"];
const PUSH_HOSTS = /^(fcm\.googleapis\.com|android\.googleapis\.com|updates\.push\.services\.mozilla\.com|web\.push\.apple\.com|[a-z0-9-]+\.notify\.windows\.com|[a-z0-9-]+\.push\.apple\.com)$/;
const UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"};
const YUA = {"User-Agent": "Mozilla/5.0"};   // Yahoo 會擋完整瀏覽器字串(429),用簡短版
const DEF = {drop: 2, win: 15, pct: -5, lim: -8, sell: 3, up: true, brief: true, b_am: true, b_open: true, b_close: true, b_inst: true, b_uso: true, b_usc: true};

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

/* 各時間點的摘要內容:回傳 null 代表資料還沒好(下一分鐘再試) */
async function genAm(T){
  const y = await spark(["^GSPC", "^IXIC", "^SOX", "TSM", "TWD=X", "^VIX"]), g = k => y[k] || {}; if (!g("^GSPC").px) return null;
  return {title: `☀️ 巴菲遠晨報 ${md(T.day)}`, body: `美股：標普 ${pc(g("^GSPC").chg, 2)}、那斯達克 ${pc(g("^IXIC").chg, 2)}、費半 ${pc(g("^SOX").chg, 2)}；台積電 ADR ${pc(g("TSM").chg, 2)}；VIX ${g("^VIX").px ? g("^VIX").px.toFixed(1) : "—"}；美元兌台幣 ${g("TWD=X").px ? g("TWD=X").px.toFixed(3) : "—"}。台股 09:00 開盤。`};
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
  return {title: `🇺🇸 美股收盤（美東 ${md(N.day)}）`, body: body + `${v ? `；VIX ${v.toFixed(1)}` : ""}。→ 台股今天開盤參考：${av >= 1 ? "偏多" : av <= -1 ? "偏空" : "持平"}（看費半與台積電 ADR，僅供參考）。`};
}

/* 存進全站時間軸,再推播給有訂閱且開著這種摘要的人 */
async function deliver(env, k, day, B){
  const DB = env.DB, now = Date.now();
  const ins = await DB.prepare("INSERT OR IGNORE INTO briefs(day,k,ts,title,body) VALUES(?,?,?,?,?)").bind(day, k, now, B.title, B.body).run();
  if (!ins.meta.changes) return 0;
  const subs = ((await DB.prepare("SELECT * FROM subs").all()).results || []).filter(s => { const c = JSON.parse(s.cfg || "{}"); return BKEY[k] in c ? !!c[BKEY[k]] : c.brief !== false; });
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

async function run(env){
  const T = tpe(), DB = env.DB, res = {};
  if (T.m == 480) { await DB.prepare("DELETE FROM alerts WHERE ts < ?").bind(Date.now() - 7 * 864e5).run(); await DB.prepare("DELETE FROM fired WHERE day < ?").bind(new Date(Date.now() - 3 * 864e5).toISOString().slice(0, 10)).run(); await DB.prepare("DELETE FROM briefs WHERE ts < ?").bind(Date.now() - 30 * 864e5).run(); }
  try { res.briefs = await briefs(env, T); } catch (e) { res.briefErr = e.message; }
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
      if (p == "/briefs") {                        // 網站「今日盤勢摘要」時間軸(公開)
        const R = (await env.DB.prepare("SELECT day,k,ts,title,body FROM briefs WHERE ts>? ORDER BY ts DESC LIMIT 14").bind(Date.now() - 4 * 864e5).all()).results || [];
        return new Response(JSON.stringify({items: R, now: Date.now()}), {headers: {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "public, max-age=60", ...cors(req)}});
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
