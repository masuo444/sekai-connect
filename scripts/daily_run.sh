#!/bin/bash
# Connect-Sekai 毎朝自動実行スクリプト
# crontab: 0 7 * * * /Users/masuo/Desktop/メディア/scripts/daily_run.sh

set -euo pipefail

PROJECT_DIR="/Users/masuo/Desktop/メディア"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"
PYTHON="/usr/bin/python3"

mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "Connect-Sekai Daily Run: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"

# 1. 全カ国の記事を自動生成（RSS→GPTリライト→DB）
echo "--- Step 1: Article Generation ---" >> "$LOG_FILE"
$PYTHON scripts/generate_all_countries.py >> "$LOG_FILE" 2>&1

# 2. サイト再生成
echo "--- Step 2: Site Generation ---" >> "$LOG_FILE"
$PYTHON -c "
import logging
logging.basicConfig(level=logging.INFO)
from src.site_generator import SiteGenerator
SiteGenerator().generate_all()
" >> "$LOG_FILE" 2>&1

echo "" >> "$LOG_FILE"
echo "Completed: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# 30日より古いログを削除
find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true
