#!/usr/bin/env python3
"""Batch thumbnail generator for Connect-Sekai articles.

Reads articles from the database that have placeholder images,
generates branded thumbnails, saves to data/images/{country}/,
and updates the visual_assets table with real image paths.

Usage:
    python scripts/generate_thumbnails.py
    python scripts/generate_thumbnails.py --country uae
    python scripts/generate_thumbnails.py --country japan --limit 5
    python scripts/generate_thumbnails.py --force          # regenerate all
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.database.models import Database
from src.images.thumbnail_generator import classify_genre, generate_thumbnail

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _load_genres_config() -> dict:
    """Load genre configuration from countries.yaml."""
    import yaml

    config_path = ROOT / "config" / "countries.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("genres", {})


def generate_all_thumbnails(
    country: str | None = None,
    limit: int | None = None,
    force: bool = False,
) -> int:
    """Generate thumbnails for articles.

    Args:
        country: Optional country filter (uae, saudi, brunei, japan).
        limit: Optional max number of thumbnails to generate.
        force: If True, regenerate all thumbnails (not just placeholders).

    Returns:
        Number of thumbnails successfully generated.
    """
    db = Database()
    db.init_db()
    genres_config = _load_genres_config()

    # Query articles
    conn = db.conn
    clauses = [
        "a.status IN ('approved', 'scheduled', 'published')",
    ]

    # Only filter for placeholder images when NOT forcing regeneration
    if not force:
        clauses.append("(va.image_path = '[placeholder]' OR va.image_path IS NULL)")

    params: list = []

    if country:
        clauses.append("a.country = ?")
        params.append(country)

    where = " AND ".join(clauses)
    query = f"""
        SELECT
            a.id AS article_id,
            a.country,
            a.title,
            a.body,
            va.id AS asset_id,
            va.image_path
        FROM articles a
        LEFT JOIN visual_assets va ON va.article_id = a.id
        WHERE {where}
        ORDER BY a.id
    """
    if limit:
        query += f" LIMIT {limit}"

    rows = conn.execute(query, params).fetchall()

    if not rows:
        logger.info("No articles need thumbnail generation.")
        db.close()
        return 0

    logger.info("Found %d articles for thumbnail generation.%s", len(rows),
                " (--force: regenerating all)" if force else "")

    success = 0
    for row in rows:
        article_id = row["article_id"]
        article_country = row["country"]
        title = row["title"] or ""
        body = row["body"] or ""
        asset_id = row["asset_id"]

        # Classify genre
        genre = classify_genre(title, body, genres_config)

        try:
            # Generate thumbnail
            output_path = generate_thumbnail(
                title=title,
                country=article_country,
                genre=genre,
                article_id=article_id,
            )

            # Update visual_assets with real path
            image_path_str = str(output_path)

            if asset_id:
                # Update existing visual_asset record
                conn.execute(
                    "UPDATE visual_assets SET image_path = ? WHERE id = ?",
                    (image_path_str, asset_id),
                )
            else:
                # No visual_asset record exists; create one
                conn.execute(
                    """INSERT INTO visual_assets
                       (article_id, image_path, prompt_used, aspect_ratio, created_at)
                       VALUES (?, ?, ?, ?, datetime('now'))""",
                    (
                        article_id,
                        image_path_str,
                        f"auto-thumbnail: {article_country}/{genre}",
                        "1200:630",
                    ),
                )
            conn.commit()
            success += 1

            logger.info(
                "  [%d/%d] article_id=%d (%s) -> %s",
                success,
                len(rows),
                article_id,
                article_country,
                output_path.name,
            )

        except Exception as e:
            logger.error(
                "  Failed article_id=%d: %s", article_id, e,
            )
            continue

    db.close()
    logger.info("Generated %d/%d thumbnails successfully.", success, len(rows))
    return success


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate thumbnail images for Connect-Sekai articles.",
    )
    parser.add_argument(
        "--country",
        type=str,
        choices=["uae", "saudi", "brunei", "japan"],
        default=None,
        help="Generate thumbnails only for this country.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of thumbnails to generate.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Regenerate all thumbnails, even if they already exist.",
    )
    args = parser.parse_args()

    count = generate_all_thumbnails(
        country=args.country,
        limit=args.limit,
        force=args.force,
    )
    logger.info("Done. %d thumbnails generated.", count)


if __name__ == "__main__":
    main()
