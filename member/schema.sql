-- 巴菲遠會員系統(D1)
CREATE TABLE IF NOT EXISTS codes (           -- 通關碼(pass)與折扣碼(disc)共用一張表
  code TEXT PRIMARY KEY, kind TEXT NOT NULL,  -- 'pass' | 'disc'
  plan TEXT, days REAL,                       -- pass:方案名稱與天數(1=一日、30=月費、可自訂)
  amount INTEGER, reuse TEXT,                 -- disc:折抵金額、'once'|'forever'
  max_dev INTEGER DEFAULT 2,                  -- pass:最多綁幾台裝置
  exp INTEGER,                                -- 碼本身的使用期限(ms;未啟用前過期就不能用)
  note TEXT, created INTEGER, revoked INTEGER DEFAULT 0,
  activated INTEGER, until INTEGER,           -- pass:第一次啟用時間、會員到期時間
  uses INTEGER DEFAULT 0                      -- disc:被套用次數
);
CREATE TABLE IF NOT EXISTS devices (code TEXT, dev TEXT, first INTEGER, last INTEGER, PRIMARY KEY (code, dev));
CREATE TABLE IF NOT EXISTS hits (ts INTEGER, day TEXT, vid TEXT, page TEXT, member INTEGER);
CREATE INDEX IF NOT EXISTS hits_day ON hits(day);
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);
