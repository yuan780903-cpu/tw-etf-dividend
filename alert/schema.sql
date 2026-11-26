-- 盤中雷達雲端推播 (D1: etf-alert)
CREATE TABLE IF NOT EXISTS subs (
  id TEXT PRIMARY KEY,
  endpoint TEXT UNIQUE NOT NULL,
  codes TEXT NOT NULL DEFAULT '[]',     -- 雷達名單 ["2330", ...]
  cfg TEXT NOT NULL DEFAULT '{}',       -- 警示條件(與網站相同)
  refs TEXT NOT NULL DEFAULT '{}',      -- 日線參考 {代號: {ma20, sup, res}}(網站開啟時同步)
  created INTEGER, updated INTEGER, fails INTEGER DEFAULT 0,
  pf TEXT NOT NULL DEFAULT '[]',        -- 配息提醒:網站「我的配息試算」持股 [{id, lots}](網站打開時同步 /pfsub)
  pfday TEXT,                           -- 配息提醒今天檢查過了沒(台北日期)
  rd INTEGER NOT NULL DEFAULT 1         -- 1=有開盤中雷達雲端監控;0=只開配息提醒(不發盤勢摘要)
);
-- 2026-11-25 既有資料庫升級用(已在遠端執行過):
--   ALTER TABLE subs ADD COLUMN pf TEXT NOT NULL DEFAULT '[]'; ALTER TABLE subs ADD COLUMN pfday TEXT; ALTER TABLE subs ADD COLUMN rd INTEGER NOT NULL DEFAULT 1;
-- 配息提醒已通知過的事件(同一件事只推一次,保留 150 天)
CREATE TABLE IF NOT EXISTS pffired (sub TEXT, k TEXT, ts INTEGER, PRIMARY KEY (sub, k));
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sub TEXT NOT NULL, ts INTEGER NOT NULL, code TEXT, title TEXT, body TEXT, bad INTEGER DEFAULT 1, sent INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS alerts_sub ON alerts(sub, sent, ts);
CREATE TABLE IF NOT EXISTS fired (sub TEXT, k TEXT, day TEXT, ts INTEGER, PRIMARY KEY (sub, k, day));
CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT, ts INTEGER);
-- 全站盤勢摘要時間軸(晨報/開盤/收盤/三大法人/美股開盤/美股收盤),每天每種一筆
CREATE TABLE IF NOT EXISTS briefs (day TEXT, k TEXT, ts INTEGER, title TEXT, body TEXT, PRIMARY KEY (day, k));
CREATE INDEX IF NOT EXISTS briefs_ts ON briefs(ts);
-- ⚡ 總經快訊(2026-11-26):k=指標:資料月份,g=US/TW,dir=偏多/偏空/中性
CREATE TABLE IF NOT EXISTS macro (k TEXT PRIMARY KEY, ts INTEGER, g TEXT, title TEXT, body TEXT, dir TEXT);
