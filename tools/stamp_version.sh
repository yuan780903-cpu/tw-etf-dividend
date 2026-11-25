#!/bin/bash
# 網站版本號:commit 前若 index.html 有改,自動蓋上 v年.月.日.當天第幾版(例:v2026.11.25.3)
# 由 .git/hooks/pre-commit 呼叫(tools/install_handoff_hook.sh 會一起安裝);也可以手動跑:tools/stamp_version.sh --force
R="$(git rev-parse --show-toplevel)"; F="$R/index.html"
if [ "$1" != "--force" ]; then
  git diff --cached --name-only | grep -qx "index.html" || exit 0      # 這次沒改網頁就不動
fi
D=$(TZ=Asia/Taipei date +%Y.%m.%d)
N=$(git log --since=midnight --format=%h -- index.html | wc -l | tr -d ' ')   # 今天已經發過幾版網頁
V="v$D.$((N + 1))"
python3 - "$F" "$V" <<'PY'
import re, sys
p, v = sys.argv[1], sys.argv[2]
s = open(p, encoding="utf-8").read()
s2 = re.sub(r'(<meta name="app-version" content=")[^"]*(")', r"\g<1>" + v + r"\g<2>", s)
s2 = re.sub(r'(<span class="app-ver"[^>]*>)[^<]*(</span>)', r"\g<1>" + v + r"\g<2>", s2)
if s2 != s:
    open(p, "w", encoding="utf-8").write(s2)
PY
git add "$F"
# 桌面工作夾的 index.html 也同步版本號(下次從桌面複製回來才不會蓋回舊版號)
W="$HOME/Desktop/claude code/網頁工具/ETF月配息/index.html"
[ -f "$W" ] && python3 - "$W" "$V" <<'PY'
import re, sys
p, v = sys.argv[1], sys.argv[2]
s = open(p, encoding="utf-8").read()
s2 = re.sub(r'(<meta name="app-version" content=")[^"]*(")', r"\g<1>" + v + r"\g<2>", s)
s2 = re.sub(r'(<span class="app-ver"[^>]*>)[^<]*(</span>)', r"\g<1>" + v + r"\g<2>", s2)
if s2 != s:
    open(p, "w", encoding="utf-8").write(s2)
PY
echo "網站版本 $V"
exit 0
