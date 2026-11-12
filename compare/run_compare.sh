#!/bin/bash
# 三平台對照：PChome / Yahoo 抓取（不開瀏覽器，不動 momo 的任何檔案）
# 用法：run_compare.sh pchome   或   run_compare.sh yahoo
cd /home/ecjerrycp/momo-sales-monitor

PLATFORM="$1"
echo "===== $(date) [compare:$PLATFORM] ====="

python3 compare/${PLATFORM}_scraper.py

git add compare/data/
git commit -m "auto: $(date '+%Y-%m-%d %H:%M') [compare:$PLATFORM] 資料更新" || echo "沒有新資料"
git pull origin main --no-edit
git push
