#!/usr/bin/env python3
"""Connect-Sekai 日刊ニュースレター送信スクリプト。

本日公開された記事を HTML メール形式で全アクティブ購読者に配信する。

実行方法:
    python scripts/send_newsletter.py

環境変数:
    SMTP_HOST          - SMTP サーバー (default: smtp.gmail.com)
    SMTP_PORT          - SMTP ポート (default: 587)
    SMTP_USER          - SMTP ユーザー名
    SMTP_PASSWORD      - SMTP パスワード
    NEWSLETTER_FROM_EMAIL - 送信元メールアドレス
    NEWSLETTER_FROM_NAME  - 送信元名 (default: Connect-Sekai 編集部)
"""

from __future__ import annotations

import logging
import os
import smtplib
import sqlite3
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# プロジェクトルート
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

# src をインポートパスに追加
import sys
sys.path.insert(0, str(_ROOT))

from src.subscribers.models import SubscriberDatabase

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SITE_URL = "https://connect-sekai.com"
WHATSAPP_CHANNEL_URL = "https://whatsapp.com/channel/PLACEHOLDER"

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_EMAIL = os.getenv("NEWSLETTER_FROM_EMAIL", "")
FROM_NAME = os.getenv("NEWSLETTER_FROM_NAME", "Connect-Sekai 編集部")

MAX_EMAILS_PER_RUN = 50

DB_PATH = _ROOT / "data" / "connect_nexus.db"

# 国名マッピング
COUNTRY_NAMES = {
    "uae": {"ja": "UAE", "icon": "&#127462;&#127466;"},
    "saudi": {"ja": "サウジアラビア", "icon": "&#127480;&#127462;"},
    "brunei": {"ja": "ブルネイ", "icon": "&#127463;&#127475;"},
    "japan": {"ja": "日本", "icon": "&#127471;&#127477;"},
}


# ---------------------------------------------------------------------------
# Database: 本日の記事を取得
# ---------------------------------------------------------------------------

def get_todays_articles() -> dict[str, list[dict[str, Any]]]:
    """本日公開された記事を国別にグループ化して返す。"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """SELECT id, country, title, body, created_at
               FROM articles
               WHERE language = 'ja'
                 AND status IN ('approved', 'scheduled', 'published')
                 AND created_at LIKE ?
               ORDER BY country, created_at DESC""",
            (f"{today}%",),
        ).fetchall()

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            d = dict(row)
            country = d["country"]
            grouped.setdefault(country, []).append(d)

        return grouped
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# HTML メールテンプレート
# ---------------------------------------------------------------------------

def _excerpt(text: str, max_len: int = 200) -> str:
    """記事本文からプレーンテキスト抜粋を生成する。"""
    if not text:
        return ""
    clean = text.replace("\n", " ").strip()
    if len(clean) <= max_len:
        return clean
    return clean[:max_len] + "..."


def build_newsletter_html(
    articles_by_country: dict[str, list[dict[str, Any]]],
    unsubscribe_url: str,
) -> str:
    """美しい HTML メールを生成する。"""
    today_str = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
    total_count = sum(len(arts) for arts in articles_by_country.values())

    # 国別セクションを構築
    country_sections = ""
    country_order = ["uae", "saudi", "brunei", "japan"]

    for country_key in country_order:
        articles = articles_by_country.get(country_key, [])
        if not articles:
            continue

        country_info = COUNTRY_NAMES.get(country_key, {"ja": country_key, "icon": ""})
        country_name = country_info["ja"]
        country_icon = country_info["icon"]

        article_items = ""
        for art in articles[:5]:
            article_url = f"{SITE_URL}/{country_key}/article-{art['id']}.html"
            excerpt = _excerpt(art.get("body", ""), 200)
            article_items += f"""
            <tr>
                <td style="padding: 16px 0; border-bottom: 1px solid #eee;">
                    <a href="{article_url}" style="color: #1B2A4A; text-decoration: none; font-size: 16px; font-weight: 600; line-height: 1.5; display: block;">
                        {art['title']}
                    </a>
                    <p style="color: #6B7280; font-size: 14px; line-height: 1.7; margin: 8px 0 0 0;">
                        {excerpt}
                    </p>
                    <a href="{article_url}" style="color: #C9A84C; font-size: 13px; font-weight: 500; text-decoration: none; display: inline-block; margin-top: 8px;">
                        &#8594; 続きを読む
                    </a>
                </td>
            </tr>"""

        country_sections += f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px;">
            <tr>
                <td style="padding: 12px 16px; background: linear-gradient(135deg, #1B2A4A 0%, #2a3f6b 100%); border-radius: 6px 6px 0 0;">
                    <span style="color: #fff; font-size: 18px; font-weight: 700;">
                        {country_icon} {country_name}
                    </span>
                    <span style="color: rgba(255,255,255,0.6); font-size: 13px; margin-left: 8px;">
                        {len(articles)} 件
                    </span>
                </td>
            </tr>
            <tr>
                <td style="padding: 0 16px; background: #fff; border: 1px solid #eee; border-top: none; border-radius: 0 0 6px 6px;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                        {article_items}
                    </table>
                </td>
            </tr>
        </table>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Connect-Sekai Daily Newsletter</title>
</head>
<body style="margin: 0; padding: 0; background: #F5F0E8; font-family: 'Helvetica Neue', Arial, 'Noto Sans JP', sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background: #F5F0E8; padding: 32px 16px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; width: 100%;">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(160deg, #1B2A4A 0%, #2a3f6b 100%); padding: 32px 24px; text-align: center; border-radius: 8px 8px 0 0;">
                            <h1 style="margin: 0; color: #fff; font-size: 28px; font-weight: 900; letter-spacing: 0.02em;">
                                Connect<span style="color: #C9A84C;">-</span>Sekai
                            </h1>
                            <p style="margin: 8px 0 0; color: rgba(255,255,255,0.7); font-size: 14px;">
                                日本とUAE・サウジアラビア・ブルネイを繋ぐビジネスメディア
                            </p>
                        </td>
                    </tr>

                    <!-- Date & Summary -->
                    <tr>
                        <td style="background: #fff; padding: 24px; border-left: 1px solid #eee; border-right: 1px solid #eee;">
                            <p style="margin: 0; color: #6B7280; font-size: 14px;">
                                {today_str}のニュースダイジェスト
                            </p>
                            <p style="margin: 8px 0 0; color: #1B2A4A; font-size: 16px; font-weight: 600;">
                                本日の記事: {total_count} 件
                            </p>
                        </td>
                    </tr>

                    <!-- Articles by Country -->
                    <tr>
                        <td style="background: #fff; padding: 8px 24px 24px; border-left: 1px solid #eee; border-right: 1px solid #eee;">
                            {country_sections}
                        </td>
                    </tr>

                    <!-- WhatsApp CTA -->
                    <tr>
                        <td style="background: #fff; padding: 0 24px 24px; border-left: 1px solid #eee; border-right: 1px solid #eee;">
                            <table width="100%" cellpadding="0" cellspacing="0" style="background: #f0faf4; border-radius: 6px; padding: 20px;">
                                <tr>
                                    <td style="padding: 20px; text-align: center;">
                                        <p style="margin: 0 0 12px; color: #1B2A4A; font-size: 15px; font-weight: 600;">
                                            WhatsApp チャンネルでもお届け中！
                                        </p>
                                        <a href="{WHATSAPP_CHANNEL_URL}" style="display: inline-block; background: #25D366; color: #fff; padding: 10px 24px; border-radius: 6px; text-decoration: none; font-size: 14px; font-weight: 600;">
                                            WhatsApp で受け取る
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background: #1B2A4A; padding: 24px; text-align: center; border-radius: 0 0 8px 8px;">
                            <p style="margin: 0; color: rgba(255,255,255,0.5); font-size: 12px; line-height: 1.7;">
                                このメールは Connect-Sekai ニュースレターの購読者に送信されています。
                            </p>
                            <p style="margin: 8px 0 0;">
                                <a href="{unsubscribe_url}" style="color: rgba(255,255,255,0.5); font-size: 12px; text-decoration: underline;">
                                    購読を解除する
                                </a>
                            </p>
                            <p style="margin: 12px 0 0; color: rgba(255,255,255,0.3); font-size: 11px;">
                                &copy; 2026 Connect-Sekai. All rights reserved.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# SMTP 送信
# ---------------------------------------------------------------------------

def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """SMTP でメールを送信する。"""
    if not SMTP_USER or not SMTP_PASSWORD or not FROM_EMAIL:
        logger.error("SMTP credentials not configured. Set SMTP_USER, SMTP_PASSWORD, NEWSLETTER_FROM_EMAIL.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = to_email

    # プレーンテキスト版 (fallback)
    plain_text = "Connect-Sekai ニュースレター\n\n最新記事は https://connect-sekai.com でご覧いただけます。"
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())
        return True
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_email, e)
        return False


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("=== Connect-Sekai Newsletter Sender START ===")

    # 本日の記事を取得
    articles_by_country = get_todays_articles()
    total_articles = sum(len(arts) for arts in articles_by_country.values())

    if total_articles == 0:
        logger.info("No articles published today. Skipping newsletter.")
        return

    logger.info("Found %d articles for today's newsletter.", total_articles)

    # 購読者データベース
    sub_db = SubscriberDatabase()
    sub_db.init_db()

    total_subscribers = sub_db.count_active_subscribers()
    if total_subscribers == 0:
        logger.info("No active subscribers. Skipping newsletter.")
        sub_db.close()
        return

    logger.info("Active subscribers: %d", total_subscribers)

    # 件名
    today_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    subject = f"[Connect-Sekai] {today_str} 本日のニュースダイジェスト ({total_articles}件)"

    # バッチ送信 (最大 50 件/回)
    sent_count = 0
    failed_count = 0
    skipped_count = 0
    offset = 0

    while offset < total_subscribers and sent_count < MAX_EMAILS_PER_RUN:
        batch_size = min(MAX_EMAILS_PER_RUN - sent_count, 50)
        subscribers = sub_db.get_active_subscribers(limit=batch_size, offset=offset)

        if not subscribers:
            break

        for sub in subscribers:
            if sent_count >= MAX_EMAILS_PER_RUN:
                break

            # 本日送信済みならスキップ
            if sub_db.was_newsletter_sent_today(sub["id"]):
                skipped_count += 1
                offset += 1
                continue

            # 購読解除 URL を構築
            unsubscribe_url = (
                f"{SITE_URL}/api/unsubscribe"
                f"?email={sub['email']}&token={sub['unsubscribe_token']}"
            )

            # HTML メールを生成
            html_body = build_newsletter_html(articles_by_country, unsubscribe_url)

            # 送信
            success = send_email(sub["email"], subject, html_body)

            if success:
                sub_db.log_newsletter_sent(
                    subscriber_id=sub["id"],
                    subject=subject,
                    article_count=total_articles,
                    status="sent",
                )
                sent_count += 1
                logger.info("Sent newsletter to: %s", sub["email"])
            else:
                sub_db.log_newsletter_sent(
                    subscriber_id=sub["id"],
                    subject=subject,
                    article_count=total_articles,
                    status="failed",
                )
                failed_count += 1
                logger.warning("Failed to send to: %s", sub["email"])

            # レート制限: 送信間隔 1 秒
            time.sleep(1)

            offset += 1

        # バッチが空でなくても、全員処理済みなら終了
        if len(subscribers) < batch_size:
            break

    sub_db.close()

    logger.info(
        "=== Newsletter Sender COMPLETE: sent=%d, failed=%d, skipped=%d ===",
        sent_count,
        failed_count,
        skipped_count,
    )


if __name__ == "__main__":
    main()
