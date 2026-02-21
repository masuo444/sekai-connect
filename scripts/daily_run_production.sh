#!/bin/bash
# ============================================================
# Connect-Sekai 本番用 毎日自動実行スクリプト
# cron: 0 22 * * * (UTC) = 毎朝7時 JST
#
# 処理フロー:
#   1. 全4カ国 × 5記事 = 20記事を自動生成
#   2. サイト再生成（HTML + sitemap）
#   3. TikTok 動画生成（記事 → 縦型動画 MP4）
#   4. X (Twitter) へ自動投稿
#   5. ニュースレター配信
#   6. ログ記録
# ============================================================

set -euo pipefail

PROJECT_DIR="/opt/connect-nexus"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"
PYTHON="$PROJECT_DIR/venv/bin/python3"

mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "Connect-Sekai Daily Run: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"

# ── 1. 全4カ国の記事を自動生成（RSS → GPTリライト → DB）──
echo "--- Step 1: Article Generation (20 articles) ---" >> "$LOG_FILE"
$PYTHON scripts/generate_all_countries.py >> "$LOG_FILE" 2>&1

# ── 2. サイト再生成 ──
echo "--- Step 2: Site Generation ---" >> "$LOG_FILE"
$PYTHON -c "
import logging
logging.basicConfig(level=logging.INFO)
from src.site_generator import SiteGenerator
SiteGenerator().generate_all()
" >> "$LOG_FILE" 2>&1

# ── 3. TikTok 動画生成（音声なし・手動アップロード用）──
echo "--- Step 3: TikTok Video Generation ---" >> "$LOG_FILE"
$PYTHON scripts/generate_tiktok_videos.py >> "$LOG_FILE" 2>&1 || {
    echo "WARNING: TikTok video generation failed (non-fatal)" >> "$LOG_FILE"
}

# ── 4. X (Twitter) 自動投稿 ──
echo "--- Step 4: Post to X (Twitter) ---" >> "$LOG_FILE"
$PYTHON scripts/post_to_x.py >> "$LOG_FILE" 2>&1 || {
    echo "WARNING: X posting failed (non-fatal)" >> "$LOG_FILE"
}

# ── 5. ニュースレター配信 ──
echo "--- Step 5: Send Newsletter ---" >> "$LOG_FILE"
$PYTHON scripts/send_newsletter.py >> "$LOG_FILE" 2>&1 || {
    echo "WARNING: Newsletter sending failed (non-fatal)" >> "$LOG_FILE"
}

# ── 6. 完了 ──
echo "" >> "$LOG_FILE"
echo "Completed: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# 30日より古いログを削除
find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true
