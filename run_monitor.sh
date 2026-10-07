#!/bin/bash
cd /home/ecjerrycp/momo-sales-monitor
source venv/bin/activate

CHECKPOINT="$1"

echo "===== $(date) [$CHECKPOINT] ====="

python3 momo_scraper.py "$CHECKPOINT"

# 只有在 close 檢查點才進行成效計算（因為要等 open+mid+close 三個檔案都齊了）
if [ "$CHECKPOINT" == "close" ]; then
    python3 compare_snapshots.py
fi

# 開檔時抓當檔新商品的 momo 分類（大類/中類），失敗不影響後面的流程
if [ "$CHECKPOINT" == "open" ]; then
    python3 fetch_momo_categories.py || echo "⚠️ 分類抓取失敗，略過"
fi

git add snapshots/
git commit -m "auto: $(date '+%Y-%m-%d %H:%M') [$CHECKPOINT] 資料更新"
git pull origin main --no-edit
git push
