#!/bin/bash
# 安裝「每次 commit 後自動產生交接包並放上 Google 雲端」（只要裝一次；換電腦重新 clone 後再跑一次）
# 取消：rm ~/repos/tw-etf-dividend/.git/hooks/post-commit
R="$(cd "$(dirname "$0")/.." && pwd)"; H="$R/.git/hooks/post-commit"
cat > "$H" <<'HOOK'
#!/bin/sh
# 巴菲遠：commit 後 10 分鐘（期間再 commit 就重新計時）自動產生交接包放上 Google 雲端，背景執行不影響 commit
R="$(git rev-parse --show-toplevel)"
[ -x "$R/tools/make_handoff.sh" ] && nohup "$R/tools/make_handoff.sh" --auto >/dev/null 2>&1 &
exit 0
HOOK
chmod +x "$H" "$R/tools/make_handoff.sh"; echo "✅ 已安裝：之後每次 commit 會自動更新雲端交接包（記錄檔 ~/Library/Logs/bfy_handoff.log）"
