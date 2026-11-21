/* 巴菲遠會員系統 Worker
   公開:GET /cfg(價格與聯絡方式)、POST /redeem(輸入折扣碼/通關碼)、GET /check(驗證會員)、POST /hit(流量)
   後台(Authorization: Bearer <ADMIN_SECRET>):/admin/* 設定價格、建立折扣碼、發通關碼、清單、作廢、統計
   不串金流:會員聯絡巴菲遠付款後,由後台發通關碼。 */
const ORIGINS = ["https://yuan780903-cpu.github.io", "http://localhost:8770"];
const AB = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";             // 去掉 O/I/0/1 避免看錯
const DEF = {prices: {day: 99, month: 599}, orig: {day: 0, month: 0}, contact: {name: "巴菲遠", line: "", phone: "", note: "付款後巴菲遠會給你一組通關碼，輸入後立即開通。"}};
const DAYMS = 864e5;
const tpe = t => new Date(t + 8 * 36e5).toISOString().slice(0, 10);   // 台北日期

function cors(req){ const o = req.headers.get("Origin") || ""; return {"Access-Control-Allow-Origin": ORIGINS.includes(o) ? o : ORIGINS[0], "Access-Control-Allow-Headers": "Content-Type, Authorization", "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Vary": "Origin"}; }
const J = (req, o, s = 200) => new Response(JSON.stringify(o), {status: s, headers: {"Content-Type": "application/json; charset=utf-8", ...cors(req)}});
const rnd = n => { const r = crypto.getRandomValues(new Uint32Array(n)); let c = ""; for (let i = 0; i < n; i++) c += AB[r[i] % AB.length]; return c; };
const norm = c => String(c || "").trim().toUpperCase().replace(/\s+/g, "");
async function getCfg(env){
  const rows = (await env.DB.prepare("SELECT k, v FROM settings").all()).results || [];
  const o = JSON.parse(JSON.stringify(DEF)); rows.forEach(r => { try { o[r.k] = Object.assign(o[r.k] || {}, JSON.parse(r.v)); } catch (e) {} });
  return o;
}
const normU = u => String(u || "").trim().toLowerCase().replace(/\s+/g, "");
const B64 = buf => btoa(String.fromCharCode(...new Uint8Array(buf)));
async function hashPw(pw, salt){                              // PBKDF2-SHA256(輕量迭代,避免超過免費版 CPU 限制)
  salt = salt || B64(crypto.getRandomValues(new Uint8Array(16)));
  const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({name: "PBKDF2", hash: "SHA-256", salt: new TextEncoder().encode(salt), iterations: 6000}, k, 256);
  return `p6k$${salt}$${B64(bits)}`;
}
const rpw = n => { const A = "abcdefghjkmnpqrstuvwxyz23456789", r = crypto.getRandomValues(new Uint32Array(n)); let c = ""; for (let i = 0; i < n; i++) c += A[r[i] % A.length]; return c; };
function eq(a, b){ if (!a || !b || a.length != b.length) return false; let x = 0; for (let i = 0; i < a.length; i++) x |= a.charCodeAt(i) ^ b.charCodeAt(i); return x == 0; }

export default {
  async fetch(req, env){
    if (req.method == "OPTIONS") return new Response(null, {headers: cors(req)});
    const url = new URL(req.url), p = url.pathname, now = Date.now();
    const body = req.method == "POST" ? await req.json().catch(() => ({})) : {};
    try {
      /* ---------- 公開 ---------- */
      if (p == "/cfg") { const c = await getCfg(env); return J(req, {ok: true, prices: c.prices, orig: c.orig, contact: c.contact}); }

      if (p == "/redeem" && req.method == "POST") {          // 同一個輸入框:通關碼→開通;折扣碼→回傳折抵
        const code = norm(body.code), dev = String(body.dev || "").slice(0, 64);
        if (!/^[0-9A-Z一-鿿]{2,24}$/.test(code)) return J(req, {ok: false, reason: "格式不對"});
        const r = await env.DB.prepare("SELECT * FROM codes WHERE code=?").bind(code).first();
        if (!r || r.revoked) return J(req, {ok: false, reason: "查無此碼或已作廢"});
        if (r.kind == "disc") {
          if (r.exp && now > r.exp) return J(req, {ok: false, reason: "折扣碼已過期"});
          if (r.reuse == "once" && r.uses > 0) return J(req, {ok: false, reason: "這組折扣碼已被使用"});
          await env.DB.prepare("UPDATE codes SET uses=uses+1 WHERE code=?").bind(code).run();
          return J(req, {ok: true, kind: "disc", code, amount: r.amount, note: r.note || ""});
        }
        // 通關碼
        if (!dev) return J(req, {ok: false, reason: "缺少裝置識別"});
        if (!r.activated && r.exp && now > r.exp) return J(req, {ok: false, reason: "通關碼已過使用期限"});
        if (r.until && now > r.until) return J(req, {ok: false, reason: "會員期間已到期", until: r.until});
        const devs = (await env.DB.prepare("SELECT dev FROM devices WHERE code=?").bind(code).all()).results.map(x => x.dev);
        if (!devs.includes(dev)) {
          if (devs.length >= (r.max_dev || 2)) return J(req, {ok: false, reason: `這組碼已綁定 ${devs.length} 台裝置，請聯絡巴菲遠`});
          await env.DB.prepare("INSERT INTO devices (code, dev, first, last) VALUES (?,?,?,?)").bind(code, dev, now, now).run();
        }
        let until = r.until;
        if (!r.activated) { until = now + r.days * DAYMS; await env.DB.prepare("UPDATE codes SET activated=?, until=? WHERE code=?").bind(now, until, code).run(); }
        return J(req, {ok: true, kind: "pass", code, plan: r.plan, until});
      }

      if (p == "/login" && req.method == "POST") {            // 會員帳號密碼登入
        const user = normU(body.user), pw = String(body.pw || ""), dev = String(body.dev || "").slice(0, 64);
        if (!user || !pw || !dev) return J(req, {ok: false, reason: "請輸入帳號和密碼"});
        const r = await env.DB.prepare("SELECT * FROM codes WHERE code=? AND kind='acct'").bind(user).first();
        const fail = async msg => { if (r) await env.DB.prepare("UPDATE codes SET fails=COALESCE(fails,0)+1, fail_at=? WHERE code=?").bind(now, user).run(); await new Promise(z => setTimeout(z, 700)); return J(req, {ok: false, reason: msg}); };
        if (!r) return fail("帳號或密碼錯誤");
        if ((r.fails || 0) >= 8 && now - (r.fail_at || 0) < 15 * 6e4) return J(req, {ok: false, reason: "密碼錯誤太多次，請 15 分鐘後再試"});
        const salt = String(r.pw || "").split("$")[1];
        if (!salt || await hashPw(pw, salt) !== r.pw) return fail("帳號或密碼錯誤");
        if (r.revoked) return J(req, {ok: false, reason: "此帳號已停用，請聯絡巴菲遠"});
        if (!r.activated && r.exp && now > r.exp) return J(req, {ok: false, reason: "帳號已過啟用期限，請聯絡巴菲遠"});
        if (r.until && now > r.until) return J(req, {ok: false, reason: "會員已到期，請聯絡巴菲遠續約", until: r.until});
        const devs = (await env.DB.prepare("SELECT dev FROM devices WHERE code=?").bind(user).all()).results.map(x => x.dev);
        if (!devs.includes(dev)) {
          if (devs.length >= (r.max_dev || 2)) return J(req, {ok: false, reason: `此帳號已在 ${devs.length} 台裝置登入，請聯絡巴菲遠重設`});
          await env.DB.prepare("INSERT INTO devices (code, dev, first, last) VALUES (?,?,?,?)").bind(user, dev, now, now).run();
        }
        let until = r.until;
        if (!r.activated) { until = now + r.days * DAYMS; await env.DB.prepare("UPDATE codes SET activated=?, until=? WHERE code=?").bind(now, until, user).run(); }
        await env.DB.prepare("UPDATE codes SET fails=0 WHERE code=?").bind(user).run();
        return J(req, {ok: true, kind: "acct", code: user, plan: r.plan, until, note: r.note || ""});
      }

      if (p == "/check") {                                    // 已開通裝置定期驗證
        const raw = url.searchParams.get("code") || "", dev = url.searchParams.get("dev") || "";
        let code = normU(raw), r = await env.DB.prepare("SELECT kind, plan, until, revoked FROM codes WHERE code=?").bind(code).first();
        if (!r) { code = norm(raw); r = await env.DB.prepare("SELECT kind, plan, until, revoked FROM codes WHERE code=?").bind(code).first(); }
        if (!r || !["pass", "acct"].includes(r.kind) || r.revoked) return J(req, {ok: true, paid: false, reason: "revoked"});
        const d = await env.DB.prepare("SELECT dev FROM devices WHERE code=? AND dev=?").bind(code, dev).first();
        if (!d) return J(req, {ok: true, paid: false, reason: "device"});
        await env.DB.prepare("UPDATE devices SET last=? WHERE code=? AND dev=?").bind(now, code, dev).run();
        return J(req, {ok: true, paid: !!r.until && now < r.until, plan: r.plan, until: r.until});
      }

      if (p == "/hit" && req.method == "POST") {               // 流量:每次開頁/切換分頁一筆
        const vid = String(body.vid || "").slice(0, 40), page = String(body.page || "").slice(0, 20);
        if (vid && page) await env.DB.prepare("INSERT INTO hits (ts, day, vid, page, member) VALUES (?,?,?,?,?)").bind(now, tpe(now), vid, page, body.m ? 1 : 0).run();
        return J(req, {ok: true});
      }

      /* ---------- 後台 ---------- */
      if (p.startsWith("/admin/")) {
        const tok = (req.headers.get("Authorization") || "").replace(/^Bearer\s+/, "");
        if (!env.ADMIN_SECRET || !eq(tok, env.ADMIN_SECRET)) { await new Promise(r => setTimeout(r, 800)); return J(req, {ok: false, reason: "密碼錯誤"}, 401); }
        const A = p.slice(7);
        if (A == "ping") return J(req, {ok: true});
        if (A == "cfg") return J(req, {ok: true, ...(await getCfg(env))});
        if (A == "cfg/set") {                                 // {prices:{day,month}, orig:{...}, contact:{...}}
          for (const k of ["prices", "orig", "contact"]) if (body[k]) await env.DB.prepare("INSERT INTO settings (k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v").bind(k, JSON.stringify(body[k])).run();
          return J(req, {ok: true});
        }
        if (A == "disc/create") {                             // {code?, amount, reuse, exp?, note?}
          const amount = Math.max(1, parseInt(body.amount) || 0), reuse = body.reuse == "once" ? "once" : "forever";
          const n = Math.min(Math.max(parseInt(body.n) || 1, 1), 100), out = [];
          for (let i = 0; i < n; i++) {
            const code = body.code && n == 1 ? norm(body.code) : rnd(8);
            if (!/^[0-9A-Z一-鿿]{2,24}$/.test(code)) return J(req, {ok: false, reason: "代碼格式不對（2～24 字中英數）"});
            const ex = await env.DB.prepare("SELECT code FROM codes WHERE code=?").bind(code).first();
            if (ex) { if (body.code) return J(req, {ok: false, reason: "這個代碼已存在"}); i--; continue; }
            await env.DB.prepare("INSERT INTO codes (code, kind, amount, reuse, exp, note, created) VALUES (?,?,?,?,?,?,?)").bind(code, "disc", amount, reuse, body.exp || null, body.note || "", now).run();
            out.push(code);
          }
          return J(req, {ok: true, codes: out});
        }
        if (A == "pass/issue") {                              // {plan, days, n, code?, maxDev, exp?, note}
          const days = Math.max(.01, parseFloat(body.days) || 1), n = Math.min(Math.max(parseInt(body.n) || 1, 1), 100), out = [];
          for (let i = 0; i < n; i++) {
            const code = body.code && n == 1 ? norm(body.code) : rnd(8);
            if (!/^[0-9A-Z一-鿿]{2,24}$/.test(code)) return J(req, {ok: false, reason: "代碼格式不對"});
            const ex = await env.DB.prepare("SELECT code FROM codes WHERE code=?").bind(code).first();
            if (ex) { if (body.code) return J(req, {ok: false, reason: "這個代碼已存在"}); i--; continue; }
            await env.DB.prepare("INSERT INTO codes (code, kind, plan, days, max_dev, exp, note, created) VALUES (?,?,?,?,?,?,?,?)").bind(code, "pass", body.plan || (days >= 28 ? "月費" : days <= 1 ? "一日" : days + " 天"), days, Math.min(Math.max(parseInt(body.maxDev) || 2, 1), 10), body.exp || null, body.note || "", now).run();
            out.push(code);
          }
          return J(req, {ok: true, codes: out});
        }
        if (A == "acct/create") {                             // {user?, pw?, plan, days, n, maxDev, exp?, note}
          const days = Math.max(.01, parseFloat(body.days) || 30), n = Math.min(Math.max(parseInt(body.n) || 1, 1), 50), out = [];
          for (let i = 0; i < n; i++) {
            const user = body.user && n == 1 ? normU(body.user) : "bfy" + rpw(5);
            if (!/^[0-9a-z_.\-一-鿿]{2,24}$/.test(user)) return J(req, {ok: false, reason: "帳號格式不對（2～24 字，英數字、底線或中文）"});
            const ex = await env.DB.prepare("SELECT code FROM codes WHERE code=?").bind(user).first();
            if (ex) { if (body.user) return J(req, {ok: false, reason: "這個帳號已存在"}); i--; continue; }
            const pw = body.pw && n == 1 ? String(body.pw) : rpw(8);
            if (pw.length < 4) return J(req, {ok: false, reason: "密碼至少 4 碼"});
            await env.DB.prepare("INSERT INTO codes (code, kind, plan, days, max_dev, exp, note, created, pw) VALUES (?,?,?,?,?,?,?,?,?)").bind(user, "acct", body.plan || (days >= 28 ? "月費" : days <= 1 ? "一日" : days + " 天"), days, Math.min(Math.max(parseInt(body.maxDev) || 2, 1), 10), body.exp || null, body.note || "", now, await hashPw(pw)).run();
            out.push({user, pw});
          }
          return J(req, {ok: true, accts: out});
        }
        if (A == "acct/resetpw") {
          const user = normU(body.code), pw = body.pw ? String(body.pw) : rpw(8);
          const r = await env.DB.prepare("SELECT code FROM codes WHERE code=? AND kind='acct'").bind(user).first();
          if (!r) return J(req, {ok: false, reason: "查無此帳號"});
          await env.DB.prepare("UPDATE codes SET pw=?, fails=0 WHERE code=?").bind(await hashPw(pw), user).run();
          return J(req, {ok: true, user, pw});
        }
        if (A == "codes") {                                    // ?kind=pass|disc
          const k = url.searchParams.get("kind") || "pass";
          const rows = (await env.DB.prepare("SELECT c.code, c.kind, c.plan, c.days, c.amount, c.reuse, c.max_dev, c.exp, c.note, c.created, c.revoked, c.activated, c.until, c.uses, (SELECT COUNT(*) FROM devices d WHERE d.code=c.code) AS ndev, (SELECT MAX(last) FROM devices d WHERE d.code=c.code) AS seen FROM codes c WHERE kind=? ORDER BY created DESC LIMIT 500").bind(k).all()).results;
          return J(req, {ok: true, rows});
        }
        const key = async c => (await env.DB.prepare("SELECT code FROM codes WHERE code=?").bind(normU(c)).first()) ? normU(c) : norm(c);
        if (A == "revoke") { await env.DB.prepare("UPDATE codes SET revoked=? WHERE code=?").bind(body.undo ? 0 : 1, await key(body.code)).run(); return J(req, {ok: true}); }
        if (A == "extend") {                                   // 會員延長 N 天
          const k = await key(body.code), r = await env.DB.prepare("SELECT until FROM codes WHERE code=? AND kind IN ('pass','acct')").bind(k).first();
          if (!r) return J(req, {ok: false, reason: "查無此帳號"});
          const base = r.until && r.until > now ? r.until : now;
          await env.DB.prepare("UPDATE codes SET until=?, activated=COALESCE(activated, ?) WHERE code=?").bind(base + (parseFloat(body.days) || 0) * DAYMS, now, k).run();
          return J(req, {ok: true});
        }
        if (A == "resetdev") { await env.DB.prepare("DELETE FROM devices WHERE code=?").bind(await key(body.code)).run(); return J(req, {ok: true}); }
        if (A == "stats") {                                    // 會員統計 + 近 N 天流量
          const days = Math.min(parseInt(url.searchParams.get("days")) || 30, 365), from = tpe(now - (days - 1) * DAYMS);
          const q = (s, ...b) => env.DB.prepare(s).bind(...b);
          const [mem, daily, pages, totals, plans, discs] = await Promise.all([
            q("SELECT SUM(CASE WHEN until>? AND revoked=0 THEN 1 ELSE 0 END) AS active, SUM(CASE WHEN until>? AND until<=? AND revoked=0 THEN 1 ELSE 0 END) AS soon, SUM(CASE WHEN activated IS NULL AND revoked=0 THEN 1 ELSE 0 END) AS unused, SUM(CASE WHEN until<=? THEN 1 ELSE 0 END) AS expired, COUNT(*) AS total FROM codes WHERE kind IN ('pass','acct')", now, now, now + 3 * DAYMS, now).first(),
            q("SELECT day, COUNT(*) AS pv, COUNT(DISTINCT vid) AS uv, COUNT(DISTINCT CASE WHEN member=1 THEN vid END) AS mv FROM hits WHERE day>=? GROUP BY day ORDER BY day", from).all(),
            q("SELECT page, COUNT(*) AS pv, COUNT(DISTINCT vid) AS uv FROM hits WHERE day>=? GROUP BY page ORDER BY pv DESC", from).all(),
            q("SELECT COUNT(*) AS pv, COUNT(DISTINCT vid) AS uv FROM hits WHERE day>=?", from).first(),
            q("SELECT plan, COUNT(*) AS n, SUM(CASE WHEN activated IS NOT NULL THEN 1 ELSE 0 END) AS used FROM codes WHERE kind IN ('pass','acct') AND revoked=0 GROUP BY plan").all(),
            q("SELECT code, amount, reuse, uses FROM codes WHERE kind='disc' AND revoked=0 ORDER BY uses DESC LIMIT 20").all()]);
          const today = (await q("SELECT COUNT(*) AS pv, COUNT(DISTINCT vid) AS uv FROM hits WHERE day=?", tpe(now)).first());
          return J(req, {ok: true, mem, daily: daily.results, pages: pages.results, totals, plans: plans.results, discs: discs.results, today});
        }
        return J(req, {ok: false, reason: "unknown"}, 404);
      }
      return J(req, {ok: false, reason: "not found"}, 404);
    } catch (e) { return J(req, {ok: false, reason: "伺服器錯誤：" + e.message}, 500); }
  },
};
