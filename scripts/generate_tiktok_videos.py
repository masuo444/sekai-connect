"""TikTok 動画を自動生成するスクリプト。

DB から本日公開された記事を取得し、GPT で要点を抽出して
1 記事につき 1 本の縦型動画 (1080x1920) を生成する。

使い方:
  python scripts/generate_tiktok_videos.py                    # 今日の全記事
  python scripts/generate_tiktok_videos.py --country uae      # UAE のみ
  python scripts/generate_tiktok_videos.py --limit 3          # 最大3本
  python scripts/generate_tiktok_videos.py --date 2026-02-20  # 日付指定

依存:
  - moviepy (ffmpeg が必要)
  - Pillow
  - openai
"""

import argparse
import logging
import re
import sys
import time
from datetime import datetime, timezone
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
# ジャンル分類 (countries.yaml のキーワードを簡易利用)
# ---------------------------------------------------------------------------

GENRE_KEYWORDS: dict[str, list[str]] = {
    "ビジネス": ["investment", "投資", "business", "ビジネス", "fund", "capital", "IPO", "M&A", "startup", "法人", "company"],
    "不動産": ["real estate", "不動産", "property", "物件", "housing", "development", "construction"],
    "ライフスタイル": ["lifestyle", "移住", "education", "教育", "visa", "ビザ", "living", "school", "health", "生活"],
    "文化": ["culture", "文化", "craft", "工芸", "halal", "ハラール", "tradition", "伝統", "art", "museum", "heritage"],
    "テクノロジー": ["technology", "テクノロジー", "AI", "tech", "digital", "blockchain", "innovation"],
    "エンターテイメント": ["entertainment", "エンタメ", "sport", "スポーツ", "tourism", "観光", "hotel", "event", "festival"],
}


def classify_genre(title: str, body: str) -> str:
    """タイトルと本文からジャンルを推定する。"""
    text = (title + " " + body).lower()
    best_genre = "ビジネス"
    best_count = 0
    for genre, keywords in GENRE_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw.lower() in text)
        if count > best_count:
            best_count = count
            best_genre = genre
    return best_genre


# ---------------------------------------------------------------------------
# GPT で要点抽出
# ---------------------------------------------------------------------------

def extract_key_points(client, title: str, body: str) -> list[str]:
    """GPT を使って記事から 3 つの要点を抽出する。

    Args:
        client: OpenAI クライアント。
        title: 記事タイトル。
        body: 記事本文。

    Returns:
        3 つの要点テキストのリスト。
    """
    # 本文が長すぎる場合は先頭 2000 文字に切り詰め
    body_trimmed = body[:2000] if len(body) > 2000 else body

    prompt = (
        "以下のビジネス記事から、TikTok動画用に3つの要点を抽出してください。\n\n"
        "【ルール】\n"
        "- 各要点は日本語で1-2文（40文字以内を目安）\n"
        "- 数字やデータがあれば優先的に含める\n"
        "- 読者が「知りたい」と思うインパクトのある内容を選ぶ\n"
        "- 絵文字は使わない\n"
        "- 各要点は改行で区切る。番号は付けない\n"
        "- 3つだけ出力する。他の説明は不要\n\n"
        f"【タイトル】\n{title}\n\n"
        f"【本文】\n{body_trimmed}\n"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=300,
            temperature=0.5,
        )
        text = response.choices[0].message.content or ""
        text = text.strip()

        # 行ごとに分割して空行を除去
        lines = [
            line.strip().lstrip("0123456789.)-）・").strip()
            for line in text.split("\n")
            if line.strip()
        ]
        # 最大 3 つ
        key_points = lines[:3]

        if len(key_points) < 3:
            logger.warning(
                "要点抽出が %d 件のみ (期待: 3 件): %s",
                len(key_points), title[:40],
            )

        return key_points

    except Exception as e:
        logger.error("要点抽出失敗: %s - %s", title[:40], e)
        # フォールバック: タイトルを要点として使用
        return [title[:40], "", ""]


# ---------------------------------------------------------------------------
# DB からの記事取得
# ---------------------------------------------------------------------------

def get_todays_articles(
    db,
    target_date: str,
    country: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """指定日の公開済み記事を取得する。

    Args:
        db: Database インスタンス。
        target_date: 取得対象日 (YYYY-MM-DD 形式)。
        country: 国キー (None の場合は全国)。
        limit: 最大取得件数。

    Returns:
        記事辞書のリスト。
    """
    clauses = [
        "status IN ('approved', 'scheduled', 'published')",
        "platform = 'web'",
        f"created_at LIKE '{target_date}%'",
    ]
    params: list = []

    if country:
        clauses.append("country = ?")
        params.append(country)

    where = " AND ".join(clauses)
    params.append(limit)

    rows = db.conn.execute(
        f"SELECT * FROM articles WHERE {where} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()

    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# スラッグ生成
# ---------------------------------------------------------------------------

def make_slug(title: str, max_len: int = 50) -> str:
    """タイトルから URL-safe なスラッグを生成する。"""
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    if not slug:
        slug = "article"
    return slug[:max_len]


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="TikTok 動画を記事から自動生成する",
    )
    parser.add_argument(
        "--country",
        choices=["uae", "saudi", "brunei", "japan"],
        default=None,
        help="対象国 (省略時: 全国)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="最大生成本数 (デフォルト: 20)",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="対象日 (YYYY-MM-DD, 省略時: 今日)",
    )
    args = parser.parse_args()

    # 対象日
    target_date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info("=== TikTok 動画生成開始 ===")
    logger.info("対象日: %s / 国: %s / 上限: %d",
                target_date, args.country or "全国", args.limit)

    # ── 依存チェック ──
    try:
        import moviepy  # noqa: F401
    except ImportError:
        logger.error(
            "moviepy がインストールされていません。\n"
            "  pip install moviepy\n"
            "また ffmpeg も必要です。\n"
            "  macOS: brew install ffmpeg\n"
            "  Ubuntu: sudo apt install ffmpeg"
        )
        sys.exit(1)

    from openai import OpenAI
    from src.database.models import Database
    from src.video.generator import TikTokVideoGenerator

    openai_client = OpenAI()
    db = Database()
    db.init_db()
    gen = TikTokVideoGenerator()

    # ── 記事取得 ──
    articles = get_todays_articles(db, target_date, args.country, args.limit)
    logger.info("対象記事: %d 件", len(articles))

    if not articles:
        logger.info("対象記事が見つかりません。終了します。")
        db.close()
        return

    # ── 動画生成ループ ──
    success = 0
    skipped = 0
    failed = 0

    for i, article in enumerate(articles):
        title = article["title"]
        body = article.get("body", "") or ""
        country = article["country"]
        hashtags = article.get("hashtags", "") or ""
        article_id = article["id"]

        logger.info("[%d/%d] %s (%s)", i + 1, len(articles), title[:50], country)

        # 出力パス
        slug = make_slug(title)
        country_dir = gen.output_dir / country
        country_dir.mkdir(parents=True, exist_ok=True)
        output_path = country_dir / f"{target_date}_{slug}.mp4"

        # 既存チェック
        if output_path.exists():
            logger.info("  → スキップ (既に生成済み): %s", output_path.name)
            skipped += 1
            continue

        # ジャンル分類
        genre = classify_genre(title, body)

        # GPT で要点抽出
        try:
            key_points = extract_key_points(openai_client, title, body)
            logger.info("  → 要点抽出OK: %s", " / ".join(kp[:20] for kp in key_points))
        except Exception as e:
            logger.error("  → 要点抽出失敗: %s", e)
            key_points = [title[:40], "", ""]

        # 動画生成
        try:
            result_path = gen.generate(
                title=title,
                body=body,
                key_points=key_points,
                country=country,
                hashtags=hashtags,
                genre=genre,
                output_path=output_path,
            )
            logger.info("  → 生成完了: %s", result_path.name)
            success += 1
        except Exception as e:
            logger.error("  → 動画生成失敗: %s", e)
            failed += 1
            continue

        # API レートリミット対策 (GPT)
        time.sleep(0.5)

    db.close()

    # ── サマリー ──
    logger.info("========================================")
    logger.info("TikTok 動画生成サマリー:")
    logger.info("  対象記事: %d 件", len(articles))
    logger.info("  生成成功: %d 件", success)
    logger.info("  スキップ: %d 件 (生成済み)", skipped)
    logger.info("  失敗:     %d 件", failed)
    logger.info("  出力先:   %s", gen.output_dir)
    logger.info("========================================")


if __name__ == "__main__":
    main()
