"""実際のUAEニュースをリサーチ → GPT-5.2が2000字の記事にリライト → サイト投稿。

シンプル版: RSS取得 → GPTリライト（プレーンテキスト）→ DB → HTML生成。
"""

import logging
import ssl
import sys
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


def fetch_uae_news(count: int = 10) -> list[dict]:
    """Google News RSS から UAE 関連ニュースを取得。"""
    import certifi
    import feedparser

    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    handler = urllib.request.HTTPSHandler(context=ssl_ctx)

    feeds = [
        "https://news.google.com/rss/search?q=Dubai+UAE+investment+business&hl=en",
        "https://news.google.com/rss/search?q=UAE+ドバイ+投資+ビジネス+不動産&hl=ja",
    ]

    articles = []
    seen = set()
    for url in feeds:
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
    return articles


def rewrite_article(client, title: str, description: str) -> dict:
    """GPT-5.2 にニュースを渡して2000字の日本語記事にリライトさせる。"""
    prompt = (
        f"あなたはConnect-Sekaiという、日本人投資家・経営者向けのUAE専門メディアのライターです。\n\n"
        f"以下のニュースを元に、日本語で約2000文字の記事を書いてください。\n\n"
        f"【元ニュース】\n"
        f"タイトル: {title}\n"
        f"概要: {description}\n\n"
        f"【ルール】\n"
        f"- 日本人の投資家・経営者が読んで「ドバイ・UAEに行きたい/投資したい」と思う切り口で書く\n"
        f"- 1行目に記事タイトル（日本語）を書き、2行目は空行、3行目から本文\n"
        f"- 知的で洗練されたトーン。煽りすぎない\n"
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

    # 1行目をタイトル、残りを本文として分離
    lines = text.split("\n", 1)
    article_title = lines[0].strip().lstrip("#").strip()
    body = lines[1].strip() if len(lines) > 1 else text

    return {
        "title": article_title,
        "body": body,
        "hashtags": "#ドバイ #UAE #海外投資 #不動産投資 #ConnectDubai",
    }


def main():
    from openai import OpenAI
    from src.database.models import Database
    from src.site_generator import SiteGenerator

    openai_client = OpenAI()
    db = Database()
    db.init_db()

    # --- ニュース取得 ---
    logger.info("=== ニュース取得中... ===")
    news_list = fetch_uae_news(10)
    logger.info("%d 件のニュースを取得", len(news_list))

    # --- GPTでリライト → DB保存 ---
    logger.info("=== GPT-5.2 で記事リライト中... ===")
    success = 0
    for i, news in enumerate(news_list):
        logger.info("[%d/%d] %s", i + 1, len(news_list), news["title"][:60])

        try:
            article = rewrite_article(openai_client, news["title"], news["description"])
            logger.info("  → 生成OK: %s (%d文字)", article["title"][:40], len(article["body"]))
        except Exception as e:
            logger.error("  → 失敗: %s", e)
            continue

        # DB保存
        news_id = db.insert_news_item(
            country="uae",
            title=news["title"],
            url=news.get("link", ""),
            source="Google News RSS",
            summary=news.get("description", "")[:200],
            relevance_score=80.0,
        )
        db.update_news_status(news_id, "processed")

        article_id = db.insert_article(
            news_item_id=news_id,
            country="uae",
            language="ja",
            platform="web",
            title=article["title"],
            body=article["body"],
            caption=article["title"][:150],
            hashtags=article["hashtags"],
        )
        db.update_article_status(article_id, "published")

        db.insert_visual_asset(
            article_id=article_id,
            image_path="[placeholder]",
            prompt_used=f"Dubai: {article['title'][:80]}",
            aspect_ratio="16:9",
        )
        success += 1

    db.close()
    logger.info("=== %d/%d 本の記事を生成完了 ===", success, len(news_list))

    # --- サイト生成 ---
    logger.info("=== サイト生成中... ===")
    SiteGenerator().generate_all()
    logger.info("=== 完了! ===")


if __name__ == "__main__":
    main()
