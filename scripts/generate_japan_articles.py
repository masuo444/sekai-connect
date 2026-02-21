"""Connect Japan の記事10本を生成する。

実際のニュースをRSSで取得し、GPT-5.2でリライト。
エンタメ枠はアニメ・漫画関連を優先的に取得する。
嘘の情報は書かない——事実に基づいたリライトのみ行う。
"""

import logging
import ssl
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── RSS フィード（ジャンル別） ──
FEEDS = {
    "business": [
        "https://news.google.com/rss/search?q=Japan+business+investment+economy+2026&hl=en",
        "https://news.google.com/rss/search?q=日本+ビジネス+経済+投資&hl=ja",
    ],
    "technology": [
        "https://news.google.com/rss/search?q=Japan+technology+AI+startup+semiconductor&hl=en",
        "https://news.google.com/rss/search?q=日本+テクノロジー+半導体+スタートアップ&hl=ja",
    ],
    "real_estate": [
        "https://news.google.com/rss/search?q=Japan+real+estate+property+Tokyo&hl=en",
        "https://news.google.com/rss/search?q=日本+不動産+東京+大阪+物件&hl=ja",
    ],
    "anime_manga": [
        "https://news.google.com/rss/search?q=anime+manga+Japan+2026&hl=en",
        "https://news.google.com/rss/search?q=アニメ+漫画+日本+新作+映画&hl=ja",
    ],
    "culture_lifestyle": [
        "https://news.google.com/rss/search?q=Japan+culture+tourism+lifestyle&hl=en",
        "https://news.google.com/rss/search?q=日本+文化+観光+ライフスタイル&hl=ja",
    ],
}

# ── ジャンル別の取得目標（合計10本） ──
TARGET = {
    "anime_manga": 4,       # エンタメ（アニメ・漫画）多め
    "business": 2,
    "technology": 2,
    "real_estate": 1,
    "culture_lifestyle": 1,
}


def fetch_news(feed_urls: list[str], count: int = 10) -> list[dict]:
    """RSSからニュースを取得する。"""
    import certifi
    import feedparser

    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    handler = urllib.request.HTTPSHandler(context=ssl_ctx)

    articles = []
    seen = set()
    for url in feed_urls:
        try:
            feed = feedparser.parse(url, handlers=[handler])
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                articles.append({
                    "title": title,
                    "description": entry.get("summary", "")[:800],
                    "link": entry.get("link", ""),
                })
                if len(articles) >= count:
                    return articles
        except Exception as e:
            logger.warning("RSS取得エラー: %s - %s", url[:60], e)
    return articles


def rewrite_article(client, title: str, description: str, genre_hint: str) -> dict:
    """GPT-5.2 でニュースを正確にリライトする。"""

    genre_instructions = {
        "anime_manga": (
            "アニメ・漫画・エンターテイメント分野の記事として書いてください。\n"
            "中東や東南アジアのアニメ・漫画ファンが読んで興味を持つ切り口で。\n"
            "日本のコンテンツ産業の最新動向として伝えてください。"
        ),
        "business": (
            "ビジネス・経済分野の記事として書いてください。\n"
            "海外の投資家・経営者が日本市場に関心を持つ切り口で。"
        ),
        "technology": (
            "テクノロジー分野の記事として書いてください。\n"
            "日本の技術力やイノベーションの最前線として伝えてください。"
        ),
        "real_estate": (
            "不動産分野の記事として書いてください。\n"
            "海外投資家が日本の不動産市場に注目する視点で。"
        ),
        "culture_lifestyle": (
            "文化・ライフスタイル分野の記事として書いてください。\n"
            "日本の文化的魅力を海外の読者に伝える切り口で。"
        ),
    }

    prompt = (
        f"あなたはConnect-Sekaiという国際ビジネスメディアのプロの編集者・ライターです。\n\n"
        f"以下のニュースを元に、日本語で約2000文字の記事を書いてください。\n\n"
        f"【元ニュース】\n"
        f"タイトル: {title}\n"
        f"概要: {description}\n\n"
        f"【ジャンル指示】\n"
        f"{genre_instructions.get(genre_hint, genre_instructions['business'])}\n\n"
        f"【絶対ルール】\n"
        f"- 事実に基づいて書くこと。嘘の情報、存在しない数字、架空の引用は絶対に書かない\n"
        f"- 元ニュースの情報をベースに、背景や文脈を補足して読み応えのある記事にする\n"
        f"- 確認できない情報は「報道によれば」「と伝えられている」等の表現を使う\n"
        f"- 1行目に記事タイトル（日本語）を書き、2行目は空行、3行目から本文\n"
        f"- 知的で洗練されたトーン。プロの編集者が書いたような文体\n"
        f"- 約2000文字\n"
        f"- JSONやマークダウンは不要。プレーンテキストのみ\n"
    )

    response = client.chat.completions.create(
        model="gpt-5.2",
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=4000,
        temperature=0.7,
    )
    text = response.choices[0].message.content or ""
    text = text.strip()

    lines = text.split("\n", 1)
    article_title = lines[0].strip().lstrip("#").strip()
    body = lines[1].strip() if len(lines) > 1 else text

    return {
        "title": article_title,
        "body": body,
    }


def main():
    from openai import OpenAI
    from src.database.models import Database
    from src.site_generator import SiteGenerator

    client = OpenAI()
    db = Database()
    db.init_db()

    total_success = 0

    for genre_key, target_count in TARGET.items():
        feed_urls = FEEDS.get(genre_key, [])
        logger.info("=== %s: %d 本目標 ===", genre_key, target_count)

        news_list = fetch_news(feed_urls, target_count * 2)
        logger.info("  %d 件のニュースを取得", len(news_list))

        genre_success = 0
        for news in news_list:
            if genre_success >= target_count:
                break

            logger.info("  [%d/%d] %s", genre_success + 1, target_count, news["title"][:60])

            try:
                article = rewrite_article(client, news["title"], news["description"], genre_key)
                logger.info("    → OK: %s (%d文字)", article["title"][:40], len(article["body"]))
            except Exception as e:
                logger.error("    → 失敗: %s", e)
                continue

            # ハッシュタグ（ジャンル別）
            hashtag_map = {
                "anime_manga": "#アニメ #漫画 #日本 #Anime #Manga #Japan #ConnectJapan",
                "business": "#日本 #ビジネス #投資 #Japan #Business #ConnectJapan",
                "technology": "#日本 #テクノロジー #Japan #Tech #Innovation #ConnectJapan",
                "real_estate": "#日本 #不動産 #東京 #Japan #RealEstate #ConnectJapan",
                "culture_lifestyle": "#日本 #文化 #Japan #Culture #ConnectJapan",
            }

            news_id = db.insert_news_item(
                country="japan",
                title=news["title"],
                url=news.get("link", ""),
                source="Google News RSS",
                summary=news.get("description", "")[:200],
                relevance_score=85.0,
            )
            db.update_news_status(news_id, "processed")

            article_id = db.insert_article(
                news_item_id=news_id,
                country="japan",
                language="ja",
                platform="web",
                title=article["title"],
                body=article["body"],
                caption=article["title"][:150],
                hashtags=hashtag_map.get(genre_key, "#日本 #ConnectJapan"),
            )
            db.update_article_status(article_id, "published")

            db.insert_visual_asset(
                article_id=article_id,
                image_path="[placeholder]",
                prompt_used=f"Japan: {article['title'][:80]}",
                aspect_ratio="16:9",
            )

            genre_success += 1
            time.sleep(1)

        total_success += genre_success
        logger.info("  %s: %d/%d 本生成完了", genre_key, genre_success, target_count)

    db.close()
    logger.info("=== 合計 %d 本の記事を生成完了 ===", total_success)

    logger.info("=== サイト再生成中... ===")
    SiteGenerator().generate_all()
    logger.info("=== 全処理完了! ===")


if __name__ == "__main__":
    main()
