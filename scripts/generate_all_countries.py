"""全3カ国（UAE, Saudi, Brunei）のニュース記事を自動生成するスクリプト。

Google News RSS → GPT-5.2 リライト（プレーンテキスト）→ DB保存 → サイト再生成。
各国5記事/日を目標とし、ブルネイのニュースが3本未満の場合は
UAE or サウジの記事を追加で生成して補填する。
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

from src.images.thumbnail_generator import classify_genre, generate_thumbnail

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 国別設定
# ---------------------------------------------------------------------------

COUNTRY_CONFIG = {
    "uae": {
        "name": "UAE",
        "feeds": [
            "https://news.google.com/rss/search?q=UAE+Dubai+Abu+Dhabi+investment+business&hl=en",
            "https://news.google.com/rss/search?q=UAE+ドバイ+アブダビ+投資+ビジネス&hl=ja",
        ],
        "target_count": 5,
        "tone": (
            "あなたはConnect-Sekaiという、日本人投資家・経営者向けのUAE専門メディアのライターです。\n"
            "投資・ラグジュアリー視点で、日本人経営者が「ドバイ・UAEに行きたい/投資したい」と思う切り口で書いてください。\n"
            "知的で洗練されたトーン。煽りすぎない。"
        ),
        "hashtags": "#ドバイ #UAE #海外投資 #不動産投資 #ConnectSekai",
    },
    "saudi": {
        "name": "Saudi Arabia",
        "feeds": [
            "https://news.google.com/rss/search?q=Saudi+Arabia+business+Vision+2030+NEOM&hl=en",
            "https://news.google.com/rss/search?q=サウジアラビア+ビジネス+投資&hl=ja",
        ],
        "target_count": 5,
        "tone": (
            "あなたはConnect-Sekaiという、日本とサウジアラビアを繋ぐメディアのライターです。\n"
            "ビジョン2030・メガプロジェクト視点で、日本文化との融合可能性を探る切り口で書いてください。\n"
            "サウジアラビアの急速な変革と、そこに日本企業・日本人が関わるチャンスを伝える。"
        ),
        "hashtags": "#サウジアラビア #ビジョン2030 #NEOM #中東ビジネス #ConnectSekai",
    },
    "brunei": {
        "name": "Brunei",
        "feeds": [
            "https://news.google.com/rss/search?q=Brunei+business+luxury+royal&hl=en",
            "https://news.google.com/rss/search?q=ブルネイ+ビジネス&hl=ja",
        ],
        "target_count": 5,
        "tone": (
            "あなたはConnect-Sekaiという、日本とブルネイを繋ぐメディアのライターです。\n"
            "王室・ハラール×日本視点で、知られざる富裕国ブルネイの魅力を伝えてください。\n"
            "ブルネイ王室の文化、ハラールビジネスと日本の伝統工芸の親和性を探る。"
        ),
        "hashtags": "#ブルネイ #富裕国 #王室 #ハラール #ConnectSekai",
    },
    "japan": {
        "name": "Japan",
        "feeds": [
            "https://news.google.com/rss/search?q=Japan+business+investment+technology+anime&hl=en",
            "https://news.google.com/rss/search?q=日本+ビジネス+投資+テクノロジー+アニメ&hl=ja",
        ],
        "target_count": 5,
        "tone": (
            "あなたはConnect-Sekaiという国際ビジネスメディアのプロの編集者です。\n"
            "日本のビジネス・テクノロジー・アニメ・漫画など、海外の投資家や日本ファンが\n"
            "興味を持つ切り口で書いてください。事実に基づき、嘘の情報は絶対に書かないこと。"
        ),
        "hashtags": "#日本 #Japan #ビジネス #テクノロジー #アニメ #ConnectJapan",
    },
}


# ---------------------------------------------------------------------------
# ニュース取得
# ---------------------------------------------------------------------------

def fetch_news(country_key: str, count: int = 10) -> list[dict]:
    """Google News RSS から指定国のニュースを取得。"""
    import certifi
    import feedparser

    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    handler = urllib.request.HTTPSHandler(context=ssl_ctx)

    config = COUNTRY_CONFIG[country_key]
    feeds = config["feeds"]

    articles: list[dict] = []
    seen: set[str] = set()
    for url in feeds:
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
            logger.warning("RSS取得エラー (%s): %s", url[:60], e)
    return articles


# ---------------------------------------------------------------------------
# GPTリライト
# ---------------------------------------------------------------------------

def rewrite_article(client, country_key: str, title: str, description: str) -> dict:
    """GPT-5.2 にニュースを渡して2000字の日本語記事にリライトさせる。"""
    config = COUNTRY_CONFIG[country_key]
    prompt = (
        f"{config['tone']}\n\n"
        f"以下のニュースを元に、日本語で約2000文字の記事を書いてください。\n\n"
        f"【元ニュース】\n"
        f"タイトル: {title}\n"
        f"概要: {description}\n\n"
        f"【ルール】\n"
        f"- 1行目に記事タイトル（日本語）を書き、2行目は空行、3行目から本文\n"
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
        "hashtags": config["hashtags"],
    }


# ---------------------------------------------------------------------------
# DB保存
# ---------------------------------------------------------------------------

def _load_genres_config() -> dict:
    """Load genre configuration from countries.yaml."""
    import yaml

    config_path = ROOT / "config" / "countries.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("genres", {})


# Cache genres config at module level (loaded lazily on first use)
_genres_config: dict | None = None


def _get_genres_config() -> dict:
    global _genres_config
    if _genres_config is None:
        _genres_config = _load_genres_config()
    return _genres_config


def save_to_db(db, country_key: str, news: dict, article: dict) -> None:
    """ニュースと記事をDBに保存し、サムネイル画像を自動生成する。"""
    news_id = db.insert_news_item(
        country=country_key,
        title=news["title"],
        url=news.get("link", ""),
        source="Google News RSS",
        summary=news.get("description", "")[:200],
        relevance_score=80.0,
    )
    db.update_news_status(news_id, "processed")

    article_id = db.insert_article(
        news_item_id=news_id,
        country=country_key,
        language="ja",
        platform="web",
        title=article["title"],
        body=article["body"],
        caption=article["title"][:150],
        hashtags=article["hashtags"],
    )
    db.update_article_status(article_id, "published")

    # Generate thumbnail image automatically
    try:
        genres_config = _get_genres_config()
        genre = classify_genre(article["title"], article["body"], genres_config)
        thumbnail_path = generate_thumbnail(
            title=article["title"],
            country=country_key,
            genre=genre,
            article_id=article_id,
        )
        image_path = str(thumbnail_path)
        logger.info("    Thumbnail generated: %s", thumbnail_path.name)
    except Exception as e:
        logger.warning("    Thumbnail generation failed: %s (using placeholder)", e)
        image_path = "[placeholder]"

    db.insert_visual_asset(
        article_id=article_id,
        image_path=image_path,
        prompt_used=f"auto-thumbnail: {country_key}/{article['title'][:80]}",
        aspect_ratio="1200:630",
    )


# ---------------------------------------------------------------------------
# 1カ国分の記事生成
# ---------------------------------------------------------------------------

def generate_for_country(client, db, country_key: str, target: int = 5) -> int:
    """指定国のニュースを取得 → GPTリライト → DB保存。生成成功数を返す。"""
    config = COUNTRY_CONFIG[country_key]
    logger.info("=== %s: ニュース取得中... ===", config["name"])

    news_list = fetch_news(country_key, count=target * 2)
    logger.info("%s: %d 件のニュースを取得", config["name"], len(news_list))

    if not news_list:
        logger.warning("%s: ニュースが取得できませんでした", config["name"])
        return 0

    success = 0
    for i, news in enumerate(news_list):
        if success >= target:
            break
        logger.info("  [%d/%d] %s", i + 1, len(news_list), news["title"][:60])

        try:
            article = rewrite_article(client, country_key, news["title"], news["description"])
            logger.info("    → 生成OK: %s (%d文字)", article["title"][:40], len(article["body"]))
        except Exception as e:
            logger.error("    → GPTリライト失敗: %s", e)
            continue

        try:
            save_to_db(db, country_key, news, article)
            success += 1
        except Exception as e:
            logger.error("    → DB保存失敗: %s", e)
            continue

        # APIレートリミット対策
        time.sleep(1)

    logger.info("=== %s: %d/%d 本の記事を生成完了 ===", config["name"], success, target)
    return success


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main():
    from openai import OpenAI
    from src.database.models import Database
    from src.site_generator import SiteGenerator

    openai_client = OpenAI()
    db = Database()
    db.init_db()

    results: dict[str, int] = {}

    # --- 全4カ国の記事生成 ---
    for country_key in ["uae", "saudi", "brunei", "japan"]:
        target = COUNTRY_CONFIG[country_key]["target_count"]
        count = generate_for_country(openai_client, db, country_key, target)
        results[country_key] = count

    # --- ブルネイ補填ロジック ---
    brunei_count = results.get("brunei", 0)
    if brunei_count < 3:
        shortfall = COUNTRY_CONFIG["brunei"]["target_count"] - brunei_count
        logger.info(
            "ブルネイが %d 本で不足（3本未満）。UAE/サウジから %d 本を追加生成します。",
            brunei_count, shortfall,
        )
        # UAE とサウジから交互に補填
        supplement_countries = ["uae", "saudi"]
        for i in range(shortfall):
            supplement_country = supplement_countries[i % len(supplement_countries)]
            extra = generate_for_country(
                openai_client, db, supplement_country, target=1,
            )
            results[supplement_country] = results.get(supplement_country, 0) + extra

    db.close()

    # --- サマリー表示 ---
    total = sum(results.values())
    logger.info("========================================")
    logger.info("全カ国記事生成サマリー:")
    for country_key, count in results.items():
        logger.info("  %s: %d 本", COUNTRY_CONFIG[country_key]["name"], count)
    logger.info("  合計: %d 本", total)
    logger.info("========================================")

    # --- サイト生成 ---
    logger.info("=== サイト再生成中... ===")
    SiteGenerator().generate_all()
    logger.info("=== 全処理完了! ===")


if __name__ == "__main__":
    main()
