#!/bin/bash
# Daily refresh for odds.socialnews.xyz — run from cron every morning.
# Fetches games, runs Jev picks, commits + pushes data.json.
# GitHub Pages redeploys automatically on push.
set -u
REPO="$HOME/workspace/sports-odds"
cd "$REPO" || exit 1

# Keep the working tree clean: stash nothing, just make sure we're on main.
git fetch -q origin 2>/dev/null
git reset -q --hard origin/main 2>/dev/null

python3 make_sports_data.py --out "$REPO" >> refresh.log 2>&1
rc=$?
if [ $rc -eq 2 ]; then
  echo "$(date -u): refresh aborted (no games fetched), data.json untouched" >> refresh.log
  exit 0
fi
if [ $rc -ne 0 ]; then
  echo "$(date -u): refresh FAILED with rc=$rc" >> refresh.log
  exit $rc
fi

if git diff --quiet data.json; then
  echo "$(date -u): no changes in data.json" >> refresh.log
  exit 0
fi

git add data.json
git commit -q -m "daily picks $(date -u +%F)" >> refresh.log 2>&1
git push -q origin main >> refresh.log 2>&1
echo "$(date -u): pushed refreshed data.json" >> refresh.log
