#!/bin/bash
# 巴菲遠：產生「交接包」新版本，放到 Google 雲端硬碟（我的雲端硬碟/claude重要檔案/巴菲遠財富系統備份/）
#   最新版/      ← 永遠是最新、沒壓縮，手機或雲端網頁可直接點開
#   歷史版本/    ← 每次一個 zip，保留最近 KEEP 個
#   版本清單.md  ← 每一版的時間、程式版本、改了什麼
# 不放任何秘密（推播私鑰、PTT 金鑰、會員資料、各種密碼），打包後還會掃描一遍，發現就中止不上傳。
# 用法：tools/make_handoff.sh          立即產生
#       tools/make_handoff.sh --auto   給 git commit 後自動呼叫：等 10 分鐘（期間又有 commit 就只跑最後一次），在背景執行
export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${BFY_WORK:-$HOME/Desktop/claude code/網頁工具/ETF月配息}"     # 桌面工作副本（交接總檔.md 在這）
PRIV="${BFY_PRIV:-$HOME/巴菲遠_私密備援}"                         # 秘密只在本機，這裡只拿來「比對」不准外流
KEEP="${BFY_KEEP:-10}"
STATE="$HOME/Library/Caches/bfy_handoff"; mkdir -p "$STATE"
LOG="$HOME/Library/Logs/bfy_handoff.log"

if [ "$1" = "--auto" ]; then
  echo $$ > "$STATE/pending"; sleep "${BFY_DELAY:-600}"
  [ "$(cat "$STATE/pending" 2>/dev/null)" = "$$" ] || exit 0       # 等待期間又有新 commit，交給新的那次
  exec >>"$LOG" 2>&1
else
  echo "manual-$$" > "$STATE/pending"                              # 手動跑過了,等待中的自動那次就不必再跑
fi
mkdir "$STATE/lock" 2>/dev/null || { echo "已有一個交接包正在產生，略過"; exit 0; }
trap 'rm -rf "$STATE/lock" "$STAGE_ROOT"' EXIT
say(){ echo "[$(date '+%F %T')] $*"; }
trunc(){ /usr/bin/python3 -c 'import sys;n=int(sys.argv[1]);[print(l if len(l)<=n else l[:n]+"…") for l in sys.stdin.read().splitlines()]' "$1"; }   # 依中文字數截斷，不切壞字

# ---- 雲端位置：自動找 Google 雲端硬碟 ----
CLOUD="${BFY_CLOUD:-}"
if [ -z "$CLOUD" ]; then
  for d in "$HOME"/Library/CloudStorage/GoogleDrive-*/我的雲端硬碟 "$HOME"/Library/CloudStorage/GoogleDrive-*/"My Drive"; do [ -d "$d" ] && { CLOUD="$d/claude重要檔案/巴菲遠財富系統備份"; break; }; done
fi
[ -n "$CLOUD" ] || { say "❌ 找不到 Google 雲端硬碟（請先開 Google Drive 電腦版），沒有上傳"; exit 1; }

cd "$REPO" || exit 1
SHA=$(git rev-parse --short HEAD); NOW=$(date '+%Y%m%d-%H%M'); NOWH=$(date '+%Y-%m-%d %H:%M')
VER="v${NOW}_${SHA}"; NAME="巴菲遠交接包_${VER}"
STAGE_ROOT=$(mktemp -d "$STATE/stage.XXXX"); S="$STAGE_ROOT/$NAME"; mkdir -p "$S"
say "開始產生 $NAME"

# ---- 01 交接總檔 ----
if [ -f "$WORK/交接總檔.md" ] && cp "$WORK/交接總檔.md" "$S/01_交接總檔.md" 2>/dev/null; then :;
elif [ -f "$CLOUD/最新版/01_交接總檔.md" ]; then cp "$CLOUD/最新版/01_交接總檔.md" "$S/01_交接總檔.md"; say "⚠️ 桌面的交接總檔讀不到，沿用雲端上一版";
else say "⚠️ 找不到交接總檔"; fi

# ---- 02 完整程式（含全部歷史）----
mkdir -p "$S/02_網站完整程式_含歷史紀錄"
git bundle create "$S/02_網站完整程式_含歷史紀錄/tw-etf-dividend.bundle" --all 2>/dev/null || { say "❌ git bundle 失敗"; exit 1; }
cat > "$S/02_網站完整程式_含歷史紀錄/還原方法.txt" <<EOF
這個 .bundle 就是整個 GitHub repo（網頁、腳本、Workers 程式、資料、全部修改歷史）。
GitHub 正常時不用它，直接：git clone https://github.com/yuan780903-cpu/tw-etf-dividend.git ~/repos/tw-etf-dividend
GitHub 不見時才用：  git clone tw-etf-dividend.bundle ~/repos/tw-etf-dividend
這一版的程式版本：$SHA（$(git log -1 --format='%ad' --date=format:'%Y-%m-%d %H:%M')）
EOF

# ---- 03 網站前端 ----
mkdir -p "$S/03_網站前端原始碼"
for f in index.html sw.js manifest.webmanifest logo.svg og.jpg favicon-32.png apple-touch-icon.png icon-192.png icon-512.png README.md; do [ -f "$f" ] && cp "$f" "$S/03_網站前端原始碼/"; done

# ---- 04 雲端 Workers ----
W="$S/04_雲端Workers程式"; mkdir -p "$W"
cp -R worker "$W/1_etf-update_一鍵更新觸發"; cp -R alert "$W/2_etf-alert_盤中推播"
cp -R member "$W/3_etf-member_會員登入後台"; cp -R proxy "$W/4_crm-proxy_報價代理"
find "$W" -name .wrangler -prune -exec rm -rf {} + 2>/dev/null

# ---- 05 資料更新腳本 ----
mkdir -p "$S/05_資料更新腳本"; cp scripts/*.py "$S/05_資料更新腳本/"
cp .github/workflows/update.yml "$S/05_資料更新腳本/GitHub雲端自動排程_update.yml"

# ---- 06 Mac／iPhone 工具 ----
mkdir -p "$S/06_Mac與iPhone工具"; cp tools/* "$S/06_Mac與iPhone工具/"
cat > "$S/06_Mac與iPhone工具/iPhone捷徑說明.txt" <<'EOF'
iPhone「PTT上傳」捷徑內含上傳金鑰，所以不放在雲端。
檔案在這台 Mac：~/巴菲遠_私密備援/PTT上傳.shortcut（用 AirDrop 傳到 iPhone 匯入）。
遺失時：在 Worker etf-update 重設 secret PTT_KEY，再請 Claude 依交接總檔重做捷徑。
iPhone 自動化：每天 08:20、12:30、15:20、21:10 執行（詳見交接總檔）。
EOF

# ---- 07 Claude 記憶 ----
M=""; for d in "$HOME"/.claude/projects/*/memory; do [ -f "$d/project_tw_etf_dividend_site.md" ] && { M="$d"; break; }; done
K="$S/07_Claude記憶_新帳號用"; mkdir -p "$K"
if [ -n "$M" ]; then
  FILES="project_tw_etf_dividend_site.md user_role.md feedback_step_by_step.md feedback_cost_sensitive.md feedback_local_only_privacy.md reference_cloudflare_worker_proxy.md reference_icloud_desktop_git_dataless.md reference_preview_launcher_desktop_path.md"
  for f in $FILES; do [ -f "$M/$f" ] && cp "$M/$f" "$K/"; done
  { echo "- 以下是 Claude 對這個專案的記憶（只挑跟巴菲遠有關的）"; for f in $FILES; do grep -F "($f)" "$M/MEMORY.md"; done; } > "$K/MEMORY.md"
fi
cat > "$K/怎麼用.txt" <<'EOF'
Claude Code（電腦版）：把這些 .md 複製到 ~/.claude/projects/<你的工作資料夾>/memory/，或直接叫 Claude「把交接包 07 的記憶裝起來」。
claude.ai 網頁版：建一個「專案」，把 00_先讀我、01_交接總檔、這裡的 .md 上傳到專案知識。
EOF

# ---- 08 版本紀錄 ----
{ echo "# 程式修改紀錄（最近 60 次）"; echo; git log -60 --date=format:'%Y-%m-%d %H:%M' --format='- %ad `%h` %s'; } > "$S/08_程式修改紀錄.md"

# ---- 00 先讀我 ----
RECENT=$(git log -15 --no-merges --date=format:'%m-%d %H:%M' --format='- %ad %s' | grep -v -E '資料更新\(|PTT 熱度' | head -8 | trunc 90)
cat > "$S/00_先讀我_新對話從這裡開始.md" <<EOF
# 巴菲遠不負責任財富系統｜交接包 $VER

- 產生時間：$NOWH（程式版本 \`$SHA\`）
- 網站：https://yuan780903-cpu.github.io/tw-etf-dividend/
- 程式：https://github.com/yuan780903-cpu/tw-etf-dividend（公開 repo，GitHub Pages 上線）

## 換新對話或新帳號，照這樣開始

1. 把這整個資料夾（或 zip 解壓後）交給 Claude：Claude Code 選這個資料夾當工作目錄；網頁版就把 00、01、07 的 .md 上傳。
2. 貼上這段開場白：

> 這是我的「巴菲遠不負責任財富系統」交接包。請先完整讀 00_先讀我_新對話從這裡開始.md 和 01_交接總檔.md，再讀 07_Claude記憶_新帳號用 裡的記憶檔。讀完用三句話告訴我系統現況和最近改了什麼，然後等我下一個指令。請用繁體中文、白話說明，一步一步做。

3. 換新電腦的話，先做下面的「新電腦還原」。

## 資料夾說明

| 資料夾 | 內容 |
|---|---|
| 00_先讀我 | 這份：怎麼接手、怎麼還原 |
| 01_交接總檔.md | 系統全貌：功能、架構、資料管線、操作、從零復原、踩過的坑、待辦 |
| 02_網站完整程式_含歷史紀錄 | 整個 repo 打包成一個檔（GitHub 不見時用它還原） |
| 03_網站前端原始碼 | index.html（整個網站就這一檔）、sw.js、圖示 |
| 04_雲端Workers程式 | Cloudflare 上 4 個小程式：一鍵更新、盤中推播、會員登入、報價代理 |
| 05_資料更新腳本 | GitHub 每天自動跑的 Python 腳本與排程設定 |
| 06_Mac與iPhone工具 | PTT 抓取、自動產生交接包的腳本、iPhone 捷徑說明 |
| 07_Claude記憶_新帳號用 | Claude 的專案記憶，新帳號照「怎麼用.txt」裝回去 |
| 08_程式修改紀錄.md | 最近 60 次修改 |

## 新電腦還原

1. 下載程式：\`git clone https://github.com/yuan780903-cpu/tw-etf-dividend.git ~/repos/tw-etf-dividend\`（GitHub 不見就用 02 的 bundle）
2. 工作副本：把 repo 複製一份到「桌面/claude code/網頁工具/ETF月配息」，交接總檔.md 也放這裡（改網頁的流程見交接總檔第五節）
3. Claude 記憶：照 07 的「怎麼用.txt」
4. 自動產生交接包：\`sh ~/repos/tw-etf-dividend/tools/install_handoff_hook.sh\`（之後每次 commit 會自動更新雲端這份）
5. 秘密：見下一節，自己的備份拿回來或重設

## 不在交接包裡的秘密（安全考量，不上雲端）

- 推播私鑰 VAPID、PTT 上傳金鑰、iPhone 捷徑、會員與推播資料庫匯出：只在原本那台 Mac 的 \`~/巴菲遠_私密備援/\`（建議另存一份隨身碟）
- 管理後台密碼、ADMIN_SECRET、GH_TOKEN、FINMIND_TOKEN：自己保管，遺失就重設（作法見交接總檔第三節「秘密放哪裡」）

## 最近改了什麼

$RECENT
EOF

# ---- 安全檢查：秘密一個都不能出現在交接包 ----
LEAK=0
if grep -rIlE 'ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----' "$S" >/dev/null 2>&1; then LEAK=1; fi
if [ -s "$PRIV/ptt_upload_key.txt" ]; then K1=$(tr -d '\r\n ' < "$PRIV/ptt_upload_key.txt"); [ -n "$K1" ] && grep -rqF -- "$K1" "$S" && LEAK=1; fi
if [ -s "$PRIV/vapid_private.jwk.json" ]; then K2=$(/usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("d",""))' "$PRIV/vapid_private.jwk.json" 2>/dev/null); [ -n "$K2" ] && grep -rqF -- "$K2" "$S" && LEAK=1; fi
unset K1 K2
[ "$LEAK" = 0 ] || { say "❌ 交接包裡發現疑似秘密，已中止、沒有上傳（請 Claude 檢查是哪個檔案）"; exit 1; }

# ---- 壓縮（中文檔名用 UTF-8，Mac／Windows 都能正常解）----
( cd "$STAGE_ROOT" && /usr/bin/python3 -m zipfile -c "$NAME.zip" "$NAME" ) || { say "❌ 壓縮失敗"; exit 1; }

# ---- 放上雲端 ----
mkdir -p "$CLOUD/最新版" "$CLOUD/歷史版本" || { say "❌ 雲端資料夾建立失敗"; exit 1; }
cp "$STAGE_ROOT/$NAME.zip" "$CLOUD/歷史版本/" || { say "❌ 上傳 zip 失敗"; exit 1; }
rsync -a --delete "$S/" "$CLOUD/最新版/" || { say "❌ 更新「最新版」失敗"; exit 1; }
echo "$VER" > "$CLOUD/最新版/版本.txt"
# 只留最近 KEEP 個 zip（舊的進雲端垃圾桶，30 天內可救回）
ls -1t "$CLOUD/歷史版本/"巴菲遠交接包_v*.zip 2>/dev/null | tail -n +$((KEEP+1)) | while read -r z; do rm -f "$z"; done

SIZE=$(du -h "$STAGE_ROOT/$NAME.zip" | cut -f1 | tr -d ' ')
LAST=$(git log -1 --format='%s' | tr '|' '/' | trunc 50)
L="$CLOUD/版本清單.md"
{ echo "# 巴菲遠財富系統｜交接包版本清單"; echo; echo "最新版直接看「最新版」資料夾；要舊版就到「歷史版本」下載 zip（保留最近 $KEEP 個）。"; echo
  echo "| 版本 | 產生時間 | 大小 | 最後一次修改 |"; echo "|---|---|---|---|"
  echo "| $VER | $NOWH | $SIZE | $LAST |"
  [ -f "$L" ] && grep -E '^\| v[0-9]' "$L" | head -199; true; } > "$STATE/list.md"; cp "$STATE/list.md" "$L"
say "✅ 完成：$NAME.zip（$SIZE）→ $CLOUD"
