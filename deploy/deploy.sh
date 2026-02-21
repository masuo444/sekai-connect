#!/bin/bash
# ============================================================
# Connect-Sekai デプロイスクリプト
# ローカルMacからVPSへプロジェクトを転送する
#
# 使い方:
#   bash deploy/deploy.sh YOUR_SERVER_IP
#   bash deploy/deploy.sh 123.45.67.89
# ============================================================

set -euo pipefail

SERVER_IP="${1:?使い方: bash deploy/deploy.sh SERVER_IP}"
SERVER_USER="connectnexus"
REMOTE_DIR="/opt/connect-nexus"
LOCAL_DIR="/Users/masuo/Desktop/メディア"

echo "========================================"
echo "  Connect-Sekai Deploy to $SERVER_IP"
echo "========================================"

# ── 1. コード転送（.env, data/, logs/ は除外）──
echo "--- Step 1: Syncing code ---"
rsync -avz --delete \
    --exclude '.env' \
    --exclude 'data/' \
    --exclude 'logs/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    --exclude 'deploy/' \
    "$LOCAL_DIR/" \
    "${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/"

# ── 2. サイトを公開ディレクトリにシンボリックリンク ──
echo "--- Step 2: Link site directory ---"
ssh "${SERVER_USER}@${SERVER_IP}" "
    ln -sfn ${REMOTE_DIR}/site /var/www/connect-nexus/site 2>/dev/null || true
    mkdir -p ${REMOTE_DIR}/logs
    mkdir -p ${REMOTE_DIR}/data
"

# ── 3. .env が無ければ作成を促す ──
echo "--- Step 3: Check .env ---"
ssh "${SERVER_USER}@${SERVER_IP}" "
    if [ ! -f ${REMOTE_DIR}/.env ]; then
        echo 'OPENAI_API_KEY=sk-your-key-here' > ${REMOTE_DIR}/.env
        echo 'GOOGLE_API_KEY=your-key-here' >> ${REMOTE_DIR}/.env
        echo ''
        echo '⚠️  .env ファイルを作成しました。APIキーを設定してください:'
        echo '  ssh ${SERVER_USER}@${SERVER_IP}'
        echo '  nano ${REMOTE_DIR}/.env'
    else
        echo '.env exists - OK'
    fi
"

# ── 4. DB初期化（初回のみ）──
echo "--- Step 4: Initialize DB ---"
ssh "${SERVER_USER}@${SERVER_IP}" "
    cd ${REMOTE_DIR}
    ${REMOTE_DIR}/venv/bin/python3 -c '
import sys
sys.path.insert(0, \".\")
from src.database.models import Database
db = Database()
db.init_db()
db.close()
print(\"DB initialized\")
'
"

# ── 5. サイト再生成 ──
echo "--- Step 5: Generate site ---"
ssh "${SERVER_USER}@${SERVER_IP}" "
    cd ${REMOTE_DIR}
    PYTHONPATH=${REMOTE_DIR} ${REMOTE_DIR}/venv/bin/python3 -c '
import logging
logging.basicConfig(level=logging.INFO)
from src.site_generator import SiteGenerator
SiteGenerator().generate_all()
'
"

echo ""
echo "========================================"
echo "  Deploy Complete!"
echo "========================================"
echo ""
echo "サイトURL: http://${SERVER_IP}"
echo ""
echo "次のステップ:"
echo "  1. APIキー設定: ssh ${SERVER_USER}@${SERVER_IP} 'nano ${REMOTE_DIR}/.env'"
echo "  2. ドメインDNS: connect-sekai.com → ${SERVER_IP}"
echo "  3. SSL証明書: ssh root@${SERVER_IP} 'certbot --nginx -d connect-sekai.com'"
echo "  4. 初回記事生成: ssh ${SERVER_USER}@${SERVER_IP} '${REMOTE_DIR}/scripts/daily_run_production.sh'"
echo ""
