"""X (Twitter) 自動投稿スクリプト。

DB に保存された当日の published 記事を GPT で要約し、
既存の TwitterClient を使ってツイートを自動投稿する。

投稿済み記事は JSON ファイルで管理し、二重投稿を防止する。
X 無料プラン（月 1,500 ツイート）を考慮し、1 回あたり最大 20 件、
各投稿間に 3 分のインターバルを設ける。
"""

import json
import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

SITE_URL = "https://connect-sekai.com"
MAX_TWEETS_PER_RUN = 20
TWEET_INTERVAL_SEC = 180  # 3 分
TWEET_MAX_CHARS = 280
POSTED_LOG_PATH = ROOT / "data" / "posted_to_x.json"


# ---------------------------------------------------------------------------
# 投稿済み管理
# ---------------------------------------------------------------------------

def load_posted_ids() -> set[int]:
    """投稿済み article_id のセットを読み込む。"""
    if not POSTED_LOG_PATH.exists():
        return set()
    try:
        data = json.loads(POSTED_LOG_PATH.read_text(encoding="utf-8"))
        return set(data.get("posted_article_ids", []))
    except (json.JSONDecodeError, KeyError):
        logger.warning("posted_to_x.json の読み込みに失敗。空として扱います。")
        return set()


def save_posted_id(article_id: int) -> None:
    """投稿済みリストに article_id を追加して保存する。"""
    posted = load_posted_ids()
    posted.add(article_id)
    data = {
        "posted_article_ids": sorted(posted),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    POSTED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSTED_LOG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 今日の記事を取得
# ---------------------------------------------------------------------------

def fetch_todays_articles(db) -> list[dict[str, Any]]:
    """DB から今日 published になった記事を取得する。"""
    today_str = date.today().isoformat()

    rows = db.conn.execute(
        """SELECT * FROM articles
           WHERE status = 'published'
             AND created_at LIKE ?
           ORDER BY id ASC""",
        (f"{today_str}%",),
    ).fetchall()

    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# GPT でツイート文を生成
# ---------------------------------------------------------------------------

def generate_tweet_text(
    openai_client,
    article: dict[str, Any],
) -> str:
    """GPT を使って記事をツイート用に要約する。"""
    title = article["title"]
    body = (article.get("body") or "")[:1500]
    country = article["country"]
    hashtags_raw = article.get("hashtags") or ""
    article_url = f"{SITE_URL}/{country}/article-{article['id']}.html"

    # ハッシュタグは最大 3 つに絞る
    all_tags = [t.strip() for t in hashtags_raw.replace(",", " ").split() if t.strip().startswith("#")]
    selected_tags = all_tags[:3]
    tags_str = " ".join(selected_tags) if selected_tags else ""

    # URL + ハッシュタグ分の文字数を確保してツイート本文の上限を算出
    reserved = len(article_url) + 1  # URL + 改行
    if tags_str:
        reserved += len(tags_str) + 1  # タグ + 改行
    max_body_chars = TWEET_MAX_CHARS - reserved - 5  # 余裕を持たせる

    prompt = (
        "あなたはConnect-Sekaiという国際ビジネスメディアの公式Xアカウント担当者です。\n"
        "以下の記事を元に、Xへの投稿文（日本語）を1つだけ作成してください。\n\n"
        f"【記事タイトル】\n{title}\n\n"
        f"【記事本文（抜粋）】\n{body}\n\n"
        "【ルール】\n"
        f"- 投稿文は{max_body_chars}文字以内（厳守）\n"
        "- 読者が記事を読みたくなるような、プロフェッショナルで魅力的な文章にする\n"
        "- メディアの公式アカウントとして、信頼感のあるトーンで書く\n"
        "- 絵文字は使わない\n"
        "- ハッシュタグ・URL は含めない（後で自動付与する）\n"
        "- 投稿文のみを出力する（説明や注釈は不要）\n"
    )

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=300,
        temperature=0.8,
    )
    tweet_body = (response.choices[0].message.content or "").strip()

    # 安全対策: 文字数オーバーを防止
    if len(tweet_body) > max_body_chars:
        tweet_body = tweet_body[: max_body_chars - 1] + "…"

    # 最終的なツイート文を組み立て
    parts = [tweet_body]
    if tags_str:
        parts.append(tags_str)
    parts.append(article_url)
    tweet = "\n".join(parts)

    return tweet


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def main() -> None:
    from openai import OpenAI

    from src.database.models import Database
    from src.sns.twitter import TwitterClient

    # --- 初期化 ---
    openai_client = OpenAI()
    db = Database()
    db.init_db()
    twitter = TwitterClient()

    if not twitter.enabled:
        logger.error(
            "TwitterClient が無効です。環境変数を確認してください: "
            "TWITTER_API_KEY, TWITTER_API_SECRET, "
            "TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET"
        )
        sys.exit(1)

    # --- 今日の記事を取得 ---
    articles = fetch_todays_articles(db)
    logger.info("本日の published 記事: %d 件", len(articles))

    if not articles:
        logger.info("投稿対象の記事がありません。終了します。")
        db.close()
        return

    # --- 投稿済みを除外 ---
    posted_ids = load_posted_ids()
    unposted = [a for a in articles if a["id"] not in posted_ids]
    logger.info("未投稿の記事: %d 件 (投稿済み: %d 件)", len(unposted), len(posted_ids & {a["id"] for a in articles}))

    if not unposted:
        logger.info("全記事が投稿済みです。終了します。")
        db.close()
        return

    # --- 投稿数上限 ---
    targets = unposted[:MAX_TWEETS_PER_RUN]
    logger.info("今回の投稿対象: %d 件 (上限: %d)", len(targets), MAX_TWEETS_PER_RUN)

    # --- 投稿ループ ---
    success_count = 0
    fail_count = 0

    for i, article in enumerate(targets):
        article_id = article["id"]
        title = article["title"]
        logger.info(
            "[%d/%d] 記事 #%d: %s",
            i + 1, len(targets), article_id, title[:50],
        )

        # --- ツイート文を生成 ---
        try:
            tweet_text = generate_tweet_text(openai_client, article)
            logger.info("  ツイート文生成OK (%d文字)", len(tweet_text))
            logger.debug("  内容: %s", tweet_text)
        except Exception as e:
            logger.error("  ツイート文生成失敗: %s", e)
            fail_count += 1
            continue

        # --- 投稿 ---
        try:
            result = twitter.publish_text_post(tweet_text)
            tweet_id = result.get("data", {}).get("id", "unknown")
            logger.info("  投稿成功! tweet_id=%s", tweet_id)
            save_posted_id(article_id)
            success_count += 1
        except Exception as e:
            logger.error("  投稿失敗: %s", e)
            fail_count += 1
            continue

        # --- インターバル（最後の投稿後は不要）---
        if i < len(targets) - 1:
            logger.info("  次の投稿まで %d 秒待機...", TWEET_INTERVAL_SEC)
            time.sleep(TWEET_INTERVAL_SEC)

    db.close()

    # --- サマリー ---
    logger.info("========================================")
    logger.info("X 投稿サマリー:")
    logger.info("  成功: %d 件", success_count)
    logger.info("  失敗: %d 件", fail_count)
    logger.info("  スキップ: %d 件", len(unposted) - len(targets))
    logger.info("========================================")


if __name__ == "__main__":
    main()
