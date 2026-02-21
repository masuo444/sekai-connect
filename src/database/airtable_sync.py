"""Optional Airtable sync for Connect-Sekai.

Pushes local SQLite data to Airtable for visual dashboard management.
Requires AIRTABLE_API_KEY and AIRTABLE_BASE_ID in the environment.
Uses the Airtable REST API directly via httpx (no extra SDK needed).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv

from src.database.models import Database

load_dotenv()
logger = logging.getLogger(__name__)

AIRTABLE_API_URL = "https://api.airtable.com/v0"


class AirtableSync:
    """Sync local SQLite records to Airtable tables."""

    # Airtable table names (must match the tables created in your base)
    TABLE_NEWS = "NewsItems"
    TABLE_ARTICLES = "Articles"
    TABLE_VISUALS = "VisualAssets"
    TABLE_QUEUE = "DistributionQueue"

    def __init__(self) -> None:
        self.api_key = os.getenv("AIRTABLE_API_KEY", "")
        self.base_id = os.getenv("AIRTABLE_BASE_ID", "")
        self.db = Database()
        self.db.init_db()

        if not self.api_key or not self.base_id:
            logger.warning(
                "AIRTABLE_API_KEY or AIRTABLE_BASE_ID not set. "
                "Airtable sync will be skipped."
            )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base_id)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _table_url(self, table_name: str) -> str:
        return f"{AIRTABLE_API_URL}/{self.base_id}/{table_name}"

    def _post_records(
        self, table_name: str, records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Create records in an Airtable table. Returns created records."""
        import httpx

        url = self._table_url(table_name)
        created: list[dict[str, Any]] = []

        # Airtable allows max 10 records per request
        for i in range(0, len(records), 10):
            batch = records[i : i + 10]
            payload = {"records": [{"fields": r} for r in batch]}
            resp = httpx.post(url, headers=self._headers(), json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            created.extend(data.get("records", []))

        return created

    # ------------------------------------------------------------------
    # Sync methods
    # ------------------------------------------------------------------

    def sync_news_items(self, limit: int = 50) -> int:
        """Push recent news_items to Airtable. Returns count synced."""
        if not self.enabled:
            return 0

        items = self.db.get_news_items(limit=limit)
        if not items:
            return 0

        records = [
            {
                "LocalID": item["id"],
                "Country": item["country"],
                "Title": item["title"],
                "URL": item.get("url", ""),
                "Source": item.get("source", ""),
                "Summary": item.get("summary", ""),
                "RelevanceScore": item.get("relevance_score", 0),
                "CollectedAt": item.get("collected_at", ""),
                "Status": item.get("status", "new"),
            }
            for item in items
        ]

        try:
            created = self._post_records(self.TABLE_NEWS, records)
            logger.info("Synced %d news items to Airtable.", len(created))
            return len(created)
        except Exception as e:
            logger.error("Failed to sync news items: %s", e)
            return 0

    def sync_articles(self, limit: int = 50) -> int:
        """Push recent articles to Airtable. Returns count synced."""
        if not self.enabled:
            return 0

        articles = self.db.get_articles(limit=limit)
        if not articles:
            return 0

        records = [
            {
                "LocalID": a["id"],
                "NewsItemID": a.get("news_item_id", 0),
                "Country": a["country"],
                "Language": a["language"],
                "Platform": a["platform"],
                "Title": a["title"],
                "Body": (a.get("body") or "")[:100000],  # Airtable text limit
                "Caption": a.get("caption", ""),
                "Hashtags": a.get("hashtags", ""),
                "HasFOMUS": bool(a.get("has_fomus_mention", 0)),
                "CreatedAt": a.get("created_at", ""),
                "Status": a.get("status", "draft"),
            }
            for a in articles
        ]

        try:
            created = self._post_records(self.TABLE_ARTICLES, records)
            logger.info("Synced %d articles to Airtable.", len(created))
            return len(created)
        except Exception as e:
            logger.error("Failed to sync articles: %s", e)
            return 0

    def sync_visual_assets(self, limit: int = 50) -> int:
        """Push recent visual assets to Airtable. Returns count synced."""
        if not self.enabled:
            return 0

        assets = self.db.get_visual_assets(limit=limit)
        if not assets:
            return 0

        records = [
            {
                "LocalID": v["id"],
                "ArticleID": v.get("article_id", 0),
                "ImagePath": v.get("image_path", ""),
                "PromptUsed": v.get("prompt_used", ""),
                "AspectRatio": v.get("aspect_ratio", ""),
                "CreatedAt": v.get("created_at", ""),
            }
            for v in assets
        ]

        try:
            created = self._post_records(self.TABLE_VISUALS, records)
            logger.info("Synced %d visual assets to Airtable.", len(created))
            return len(created)
        except Exception as e:
            logger.error("Failed to sync visual assets: %s", e)
            return 0

    def sync_distribution_queue(self, limit: int = 50) -> int:
        """Push distribution queue entries to Airtable. Returns count synced."""
        if not self.enabled:
            return 0

        queue = self.db.get_distribution_queue(limit=limit)
        if not queue:
            return 0

        records = [
            {
                "LocalID": d["id"],
                "ArticleID": d.get("article_id", 0),
                "VisualAssetID": d.get("visual_asset_id", 0),
                "Platform": d["platform"],
                "ScheduledTime": d.get("scheduled_time", ""),
                "Timezone": d.get("timezone", ""),
                "PublishedAt": d.get("published_at") or "",
                "Status": d.get("status", "pending"),
            }
            for d in queue
        ]

        try:
            created = self._post_records(self.TABLE_QUEUE, records)
            logger.info("Synced %d queue entries to Airtable.", len(created))
            return len(created)
        except Exception as e:
            logger.error("Failed to sync queue entries: %s", e)
            return 0

    def sync_all(self, limit: int = 50) -> dict[str, int]:
        """Sync all tables to Airtable. Returns {table: count_synced}."""
        if not self.enabled:
            logger.info("Airtable sync disabled (no credentials).")
            return {}

        return {
            "news_items": self.sync_news_items(limit),
            "articles": self.sync_articles(limit),
            "visual_assets": self.sync_visual_assets(limit),
            "distribution_queue": self.sync_distribution_queue(limit),
        }
