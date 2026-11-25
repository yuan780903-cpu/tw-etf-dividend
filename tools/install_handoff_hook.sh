#!/bin/bash
# 安裝兩個 git hook（只要裝一次；換電腦重新 clone 後再跑一次）：
#   pre-commit  網頁有改就自動蓋上版本號（tools/stamp_version.sh）
#   post-commit 每次 commit 後自動產生交接包並放上 Google 雲端
# 取消：rm ~/repos/tw-etf-dividend/.git/hooks/post-commit ~/repos/tw-etf-dividend/.git/hooks/pre-commit
R="$(cd "$(dirname "$0")/.." && pwd)"; H="$R/.git/hooks/post-commit"
cat > "$H" <<'HOOK'
#!/bin/sh
# 巴菲遠：commit 後 10 分鐘（期間再 commit 就重新計時）自動產生交接包放上 Google 雲端，背景執行不影響 commit
R="$(git rev-parse --show-toplevel)"
[ -x "$R/tools/make_handoff.sh" ] && nohup "$R/tools/make_handoff.sh" --auto >/dev/null 2>&1 &
exit 0
HOOK
# commit 前:網頁有改就自動蓋上版本號(v年.月.日.當天第幾版)
P="$R/.git/hooks/pre-commit"
cat > "$P" <<'HOOK'
#!/bin/sh
R="$(git rev-parse --show-toplevel)"
[ -x "$R/tools/stamp_version.sh" ] && "$R/tools/stamp_version.sh"
exit 0
HOOK
chmod +x "$H" "$P" "$R/tools/make_handoff.sh" "$R/tools/stamp_version.sh"
echo "✅ 已安裝：commit 前自動蓋網站版本號；commit 後自動更新雲端交接包（記錄檔 ~/Library/Logs/bfy_handoff.log）"
