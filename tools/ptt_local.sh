#!/bin/bash
# 巴菲遠:PTT 股版熱度改由「這台 Mac」抓(PTT 會擋 GitHub 雲端主機,家裡網路正常可看),抓完推上 GitHub,網站自動顯示新資料
# 由 ~/Library/LaunchAgents/com.bafeiyuan.ptt.plist 每天 08:10、12:40、15:50、21:10 執行(Mac 睡眠中錯過的,醒來會補跑一次)
# 用獨立的淺層複本 ~/repos/.ptt-runner,不會動到你正在改的 ~/repos/tw-etf-dividend
export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
[ -t 1 ] || exec >>"$HOME/Library/Logs/bafeiyuan_ptt.log" 2>&1   # 排程執行時寫到記錄檔
R="$HOME/repos/.ptt-runner"; TMP="$(mktemp -t ptt)"
echo "== $(date '+%F %T') 開始"
if [ ! -d "$R/.git" ]; then git clone -q --depth 1 https://github.com/yuan780903-cpu/tw-etf-dividend.git "$R" || exit 1; fi
cd "$R" || exit 1
git config user.name "etf-bot-mac"; git config user.email "etf-bot@users.noreply.github.com"
git fetch -q --depth 1 origin main && git reset -q --hard origin/main || exit 1
/usr/bin/python3 scripts/fetch_ptt.py || exit 1
cp data/ptt.json "$TMP"
for i in 1 2 3; do                                  # 雲端也在推資料:每次都對齊最新 main 再放上 ptt.json
  git fetch -q --depth 1 origin main && git reset -q --hard origin/main
  cp "$TMP" data/ptt.json; git add data/ptt.json
  if git diff --cached --quiet; then echo "沒有變化"; rm -f "$TMP"; exit 0; fi
  git commit -q -m "PTT 熱度(Mac) $(date '+%Y-%m-%d %H:%M')" && git push -q origin HEAD:main && { echo "已推上 GitHub"; rm -f "$TMP"; exit 0; }
  sleep 15
done
echo "推送失敗"; exit 1
