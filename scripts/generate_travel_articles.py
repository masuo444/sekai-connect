"""UAE 5本 + サウジ 5本の旅行記事を生成するスクリプト。

GPT-5.2でConnect-Sekaiの旅行ガイド記事を生成し、DB保存 → サイト再生成。
ニュースベースではなく、固定トピックに基づく実用的な旅行ガイド記事。
"""

import logging
import sys
import time
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

# ---------------------------------------------------------------------------
# 旅行記事トピック定義
# ---------------------------------------------------------------------------

TRAVEL_TOPICS = {
    "uae": [
        {
            "topic": "UAE入国完全ガイド",
            "prompt_detail": (
                "UAE入国完全ガイドを書いてください。以下の内容を網羅すること:\n"
                "- ビザの種類（観光ビザ、ビジネスビザ、ゴールデンビザ、トランジットビザ）\n"
                "- 各ビザの申請方法、必要書類、費用\n"
                "- ゴールデンビザの取得条件（不動産投資額、起業家枠など）\n"
                "- 入国時の注意点（持ち込み禁止品、税関手続き）\n"
                "- 日本のパスポートでの入国の容易さ"
            ),
            "hashtags": "#UAE入国 #ドバイビザ #ゴールデンビザ #海外渡航 #ConnectSekai",
        },
        {
            "topic": "ドバイ・アブダビ交通完全ガイド",
            "prompt_detail": (
                "ドバイ・アブダビの交通完全ガイドを書いてください。以下の内容を網羅すること:\n"
                "- ドバイメトロ（路線図、料金、Nolカード）\n"
                "- タクシー・配車アプリ（Uber、Careem）の使い方と相場\n"
                "- レンタカー（国際免許、交通ルール、駐車場事情）\n"
                "- ドバイ⇔アブダビの長距離移動（バス、タクシー、所要時間）\n"
                "- 空港からの市内アクセス（ドバイ国際空港、アブダビ国際空港）"
            ),
            "hashtags": "#ドバイ交通 #ドバイメトロ #UAE旅行 #海外交通 #ConnectSekai",
        },
        {
            "topic": "UAE安全・マナーガイド",
            "prompt_detail": (
                "UAEの安全・マナーガイドを書いてください。以下の内容を網羅すること:\n"
                "- 治安レベル（世界安全ランキング、夜間の安全性）\n"
                "- 法律上の注意点（飲酒規制、写真撮影、SNS投稿の注意）\n"
                "- ドレスコード（ショッピングモール、ビーチ、モスク訪問時）\n"
                "- ラマダン中の過ごし方（飲食制限、営業時間変更）\n"
                "- 日本人が特に気をつけるべきポイント"
            ),
            "hashtags": "#UAE安全 #ドバイマナー #ラマダン #海外安全 #ConnectSekai",
        },
        {
            "topic": "UAE宿泊完全ガイド",
            "prompt_detail": (
                "UAEの宿泊完全ガイドを書いてください。以下の内容を網羅すること:\n"
                "- ドバイのエリア別ホテル選び（ダウンタウン、マリーナ、デイラ、パームジュメイラ）\n"
                "- アブダビのエリア別ホテル選び（コーニッシュ、サディヤット島、ヤス島）\n"
                "- サービスアパートメントという選択肢（長期滞在向け）\n"
                "- 予算別おすすめ（1泊5000円〜、1泊2万円〜、1泊5万円以上）\n"
                "- 予約のコツ（ベストシーズン、早割、ポイントプログラム）"
            ),
            "hashtags": "#ドバイホテル #UAE宿泊 #海外ホテル #旅行準備 #ConnectSekai",
        },
        {
            "topic": "UAEグルメ完全ガイド",
            "prompt_detail": (
                "UAEのグルメ完全ガイドを書いてください。以下の内容を網羅すること:\n"
                "- ハラール食の基本（日本人が知っておくべきこと）\n"
                "- ドバイ・アブダビの日本食レストラン（おすすめ5選）\n"
                "- 必食のローカルフード（シャワルマ、マンディ、ルクマット等）\n"
                "- 高級ダイニング（ミシュラン星付き、セレブ御用達）\n"
                "- フードコート・ストリートフードの楽しみ方と相場感"
            ),
            "hashtags": "#ドバイグルメ #UAEフード #ハラール #海外グルメ #ConnectSekai",
        },
    ],
    "saudi": [
        {
            "topic": "サウジアラビア入国完全ガイド",
            "prompt_detail": (
                "サウジアラビア入国完全ガイドを書いてください。以下の内容を網羅すること:\n"
                "- 電子ビザ（eVisa）の申請方法、必要書類、費用\n"
                "- ビジネスビザの取得方法\n"
                "- ウムラビザについて\n"
                "- 入国時の注意点（持ち込み禁止品、税関手続き）\n"
                "- 日本のパスポートでの渡航の流れ\n"
                "- 最新の規制緩和情報（観光開放の現状）"
            ),
            "hashtags": "#サウジ入国 #サウジビザ #サウジアラビア旅行 #海外渡航 #ConnectSekai",
        },
        {
            "topic": "サウジアラビア交通ガイド",
            "prompt_detail": (
                "サウジアラビアの交通ガイドを書いてください。以下の内容を網羅すること:\n"
                "- リヤドの交通事情（メトロ開業状況、タクシー、配車アプリ）\n"
                "- ジェッダの交通事情（市内移動、空港アクセス）\n"
                "- 配車アプリ（Uber、Careem）の使い方と相場\n"
                "- 都市間移動（リヤド⇔ジェッダ、国内線、長距離バス、ハラマイン高速鉄道）\n"
                "- レンタカー（運転免許、交通ルール、ガソリン価格）"
            ),
            "hashtags": "#サウジ交通 #リヤド #ジェッダ #海外交通 #ConnectSekai",
        },
        {
            "topic": "サウジアラビア安全・マナーガイド",
            "prompt_detail": (
                "サウジアラビアの安全・マナーガイドを書いてください。以下の内容を網羅すること:\n"
                "- 服装規定（男性・女性それぞれ、アバヤは必要か）\n"
                "- 宗教的配慮（祈りの時間、モスクでのマナー）\n"
                "- 飲酒・豚肉の完全禁止について\n"
                "- 女性旅行者向け情報（最新の規制緩和、一人旅は可能か）\n"
                "- 写真撮影・SNSの注意点\n"
                "- 日本人が特に気をつけるべきポイント"
            ),
            "hashtags": "#サウジマナー #サウジアラビア安全 #女性旅行 #海外安全 #ConnectSekai",
        },
        {
            "topic": "サウジアラビア宿泊ガイド",
            "prompt_detail": (
                "サウジアラビアの宿泊ガイドを書いてください。以下の内容を網羅すること:\n"
                "- リヤドのエリア別ホテル選び（オラヤ通り、キングアブドゥラ・ファイナンシャル地区）\n"
                "- ジェッダのエリア別ホテル選び（コーニッシュ、歴史地区周辺）\n"
                "- NEOM周辺の宿泊事情（開発中エリアの現状）\n"
                "- 予算別おすすめ（エコノミー、ビジネス、ラグジュアリー）\n"
                "- 予約時の注意点（ハッジ・ウムラシーズンの高騰）"
            ),
            "hashtags": "#サウジホテル #リヤド宿泊 #ジェッダ宿泊 #海外ホテル #ConnectSekai",
        },
        {
            "topic": "サウジアラビア観光スポット完全ガイド",
            "prompt_detail": (
                "サウジアラビアの観光スポット完全ガイドを書いてください。以下の内容を網羅すること:\n"
                "- NEOM（未来都市プロジェクト THE LINE、トロジェナ、訪問可能か）\n"
                "- AlUla遺跡（ヘグラ遺跡、UNESCO世界遺産、アクセス方法）\n"
                "- 紅海リゾート（アマラ・プロジェクト、ダイビング）\n"
                "- ディルイーヤ（サウド家発祥の地、歴史地区）\n"
                "- ジェッダ歴史地区（アル・バラド、UNESCO世界遺産）\n"
                "- エンタメ施設（ブールバード・リヤド、シックスフラッグス計画）"
            ),
            "hashtags": "#サウジ観光 #NEOM #AlUla #紅海 #ConnectSekai",
        },
    ],
}


# ---------------------------------------------------------------------------
# GPT記事生成
# ---------------------------------------------------------------------------

def generate_travel_article(client, country_key: str, topic_info: dict) -> dict:
    """GPT-5.2 で旅行ガイド記事を生成する。"""
    country_name = "UAE" if country_key == "uae" else "サウジアラビア"
    prompt = (
        f"あなたはConnect-Sekaiの旅行ライターです。\n"
        f"日本人読者向けに、{country_name}の旅行ガイド記事を書いてください。\n\n"
        f"【テーマ】\n{topic_info['topic']}\n\n"
        f"【執筆指示】\n{topic_info['prompt_detail']}\n\n"
        f"【ルール】\n"
        f"- 1行目に記事タイトル（日本語）を書き、2行目は空行、3行目から本文\n"
        f"- 実用的で詳細な情報を中心に（具体的な金額、手順、注意点）\n"
        f"- 約2500〜3000文字\n"
        f"- 「これを読めば安心して渡航できる」レベルの情報量\n"
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
        "hashtags": topic_info["hashtags"],
    }


# ---------------------------------------------------------------------------
# DB保存
# ---------------------------------------------------------------------------

def save_travel_article_to_db(db, country_key: str, topic_info: dict, article: dict) -> None:
    """旅行記事をDBに保存する。"""
    news_id = db.insert_news_item(
        country=country_key,
        title=topic_info["topic"],
        url="",
        source="Connect-Sekai Travel Guide",
        summary=f"旅行ガイド: {topic_info['topic']}",
        relevance_score=90.0,
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

    db.insert_visual_asset(
        article_id=article_id,
        image_path="[placeholder]",
        prompt_used=f"Travel: {article['title'][:80]}",
        aspect_ratio="16:9",
    )


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

    results: dict[str, int] = {"uae": 0, "saudi": 0}

    for country_key in ["uae", "saudi"]:
        topics = TRAVEL_TOPICS[country_key]
        country_name = "UAE" if country_key == "uae" else "サウジアラビア"
        logger.info("========================================")
        logger.info("=== %s 旅行記事生成開始 (%d本) ===", country_name, len(topics))
        logger.info("========================================")

        for i, topic_info in enumerate(topics):
            logger.info("[%d/%d] %s", i + 1, len(topics), topic_info["topic"])

            try:
                article = generate_travel_article(openai_client, country_key, topic_info)
                logger.info("  → 生成OK: %s (%d文字)", article["title"][:40], len(article["body"]))
            except Exception as e:
                logger.error("  → GPT生成失敗: %s", e)
                continue

            try:
                save_travel_article_to_db(db, country_key, topic_info, article)
                results[country_key] += 1
                logger.info("  → DB保存完了")
            except Exception as e:
                logger.error("  → DB保存失敗: %s", e)
                continue

            # APIレートリミット対策
            time.sleep(2)

    db.close()

    # --- サマリー表示 ---
    total = sum(results.values())
    logger.info("========================================")
    logger.info("旅行記事生成サマリー:")
    logger.info("  UAE: %d 本", results["uae"])
    logger.info("  サウジアラビア: %d 本", results["saudi"])
    logger.info("  合計: %d 本", total)
    logger.info("========================================")

    # --- サイト生成 ---
    logger.info("=== サイト再生成中... ===")
    SiteGenerator().generate_all()
    logger.info("=== 全処理完了! ===")


if __name__ == "__main__":
    main()
