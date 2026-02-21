#!/bin/bash
# ============================================================
# Connect-Sekai VPS 初期セットアップスクリプト
# 対象: Ubuntu 22.04 / 24.04 LTS
#
# 使い方:
#   1. VPS を契約（DigitalOcean, Vultr, Linode 等 — $5/月〜）
#   2. SSH でログイン: ssh root@YOUR_SERVER_IP
#   3. このスクリプトを転送して実行:
#      scp deploy/setup_server.sh root@YOUR_SERVER_IP:/tmp/
#      ssh root@YOUR_SERVER_IP 'bash /tmp/setup_server.sh'
# ============================================================

set -euo pipefail

echo "========================================"
echo "  Connect-Sekai Server Setup"
echo "========================================"

# ── 1. システム更新 ──
echo "--- Step 1: System update ---"
apt update && apt upgrade -y

# ── 2. 必要パッケージのインストール ──
echo "--- Step 2: Install packages ---"
apt install -y \
    python3 python3-pip python3-venv \
    nginx certbot python3-certbot-nginx \
    git curl ufw

# ── 3. ファイアウォール設定 ──
echo "--- Step 3: Firewall setup ---"
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# ── 4. プロジェクトユーザー作成 ──
echo "--- Step 4: Create app user ---"
if ! id "connectnexus" &>/dev/null; then
    useradd -m -s /bin/bash connectnexus
    echo "User 'connectnexus' created."
fi

# ── 5. プロジェクトディレクトリ作成 ──
echo "--- Step 5: Create directories ---"
mkdir -p /var/www/connect-nexus
mkdir -p /opt/connect-nexus
chown -R connectnexus:connectnexus /var/www/connect-nexus
chown -R connectnexus:connectnexus /opt/connect-nexus

# ── 6. Python 仮想環境作成 ──
echo "--- Step 6: Python venv ---"
sudo -u connectnexus python3 -m venv /opt/connect-nexus/venv
sudo -u connectnexus /opt/connect-nexus/venv/bin/pip install --upgrade pip
sudo -u connectnexus /opt/connect-nexus/venv/bin/pip install \
    openai python-dotenv feedparser certifi pyyaml jinja2 google-generativeai

# ── 7. Nginx 設定 ──
echo "--- Step 7: Nginx config ---"
cat > /etc/nginx/sites-available/connect-nexus << 'NGINX_EOF'
server {
    listen 80;
    server_name connect-sekai.com www.connect-sekai.com;

    root /var/www/connect-nexus/site;
    index index.html;
    charset utf-8;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    gzip on;
    gzip_types text/plain text/css text/xml application/json application/javascript text/javascript application/xml+rss image/svg+xml;
    gzip_min_length 256;
    gzip_vary on;

    location ~* \.(css|js|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location ~* \.html$ {
        expires 1h;
        add_header Cache-Control "public, must-revalidate";
    }

    location / {
        try_files $uri $uri/ $uri/index.html =404;
    }

    error_page 404 /index.html;
}
NGINX_EOF

ln -sf /etc/nginx/sites-available/connect-nexus /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# ── 8. Cron ジョブ設定（毎朝7時 JST = UTC 22:00 前日）──
echo "--- Step 8: Cron setup ---"
CRON_CMD="0 22 * * * /opt/connect-nexus/scripts/daily_run_production.sh >> /opt/connect-nexus/logs/cron.log 2>&1"
(sudo -u connectnexus crontab -l 2>/dev/null || true; echo "$CRON_CMD") | sort -u | sudo -u connectnexus crontab -

echo ""
echo "========================================"
echo "  Setup Complete!"
echo "========================================"
echo ""
echo "次のステップ:"
echo "  1. ローカルからデプロイ: bash deploy/deploy.sh YOUR_SERVER_IP"
echo "  2. .env ファイルにAPIキーを設定"
echo "  3. ドメインのDNSをサーバーIPに向ける"
echo "  4. SSL証明書取得: sudo certbot --nginx -d connect-sekai.com -d www.connect-sekai.com"
echo ""
