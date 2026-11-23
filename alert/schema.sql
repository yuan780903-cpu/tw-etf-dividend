-- 盤中雷達雲端推播 (D1: etf-alert)
CREATE TABLE IF NOT EXISTS subs (
  id TEXT PRIMARY KEY,
  endpoint TEXT UNIQUE NOT NULL,
  codes TEXT NOT NULL DEFAULT '[]',     -- 雷達名單 ["2330", ...]
  cfg TEXT NOT NULL DEFAULT '{}',       -- 警示條件(與網站相同)
  refs TEXT NOT NULL DEFAULT '{}',      -- 日線參考 {代號: {ma20, sup, res}}(網站開啟時同步)
  created INTEGER, updated INTEGER, fails INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sub TEXT NOT NULL, ts INTEGER NOT NULL, code TEXT, title TEXT, body TEXT, bad INTEGER DEFAULT 1, sent INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS alerts_sub ON alerts(sub, sent, ts);
CREATE TABLE IF NOT EXISTS fired (sub TEXT, k TEXT, day TEXT, ts INTEGER, PRIMARY KEY (sub, k, day));
CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT, ts INTEGER);
