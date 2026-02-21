"""SQLite database management for Connect-Sekai."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = _ROOT / "data" / "connect_nexus.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS news_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    country         TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    url             TEXT,
    source          TEXT,
    summary         TEXT,
    relevance_score REAL    DEFAULT 0,
    collected_at    TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'processed', 'archived'))
);

CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    news_item_id    INTEGER REFERENCES news_items(id),
    country         TEXT    NOT NULL,
    language        TEXT    NOT NULL CHECK (language IN ('ja', 'en', 'ar', 'ms')),
    platform        TEXT    NOT NULL CHECK (platform IN ('instagram', 'tiktok', 'twitter', 'web')),
    title           TEXT    NOT NULL,
    body            TEXT,
    caption         TEXT,
    hashtags        TEXT,
    has_fomus_mention INTEGER DEFAULT 0,
    created_at      TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'approved', 'scheduled', 'published'))
);

CREATE TABLE IF NOT EXISTS visual_assets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id      INTEGER REFERENCES articles(id),
    image_path      TEXT    NOT NULL,
    prompt_used     TEXT,
    aspect_ratio    TEXT,
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS distribution_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id      INTEGER REFERENCES articles(id),
    visual_asset_id INTEGER REFERENCES visual_assets(id),
    platform        TEXT    NOT NULL,
    scheduled_time  TEXT    NOT NULL,
    timezone        TEXT,
    published_at    TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'published', 'failed'))
);
"""


class Database:
    """Thin wrapper around SQLite for Connect-Sekai data operations."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Create all tables if they do not exist."""
        self.conn.executescript(_SCHEMA_SQL)
        self.conn.commit()
        logger.info("Database initialized at %s", self.db_path)

    # ------------------------------------------------------------------
    # news_items CRUD
    # ------------------------------------------------------------------

    def insert_news_item(
        self,
        country: str,
        title: str,
        url: str = "",
        source: str = "",
        summary: str = "",
        relevance_score: float = 0,
    ) -> int:
        """Insert a news item and return its id."""
        cur = self.conn.execute(
            """INSERT INTO news_items
               (country, title, url, source, summary, relevance_score, collected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                country,
                title,
                url,
                source,
                summary,
                relevance_score,
                _now(),
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_news_items(
        self,
        country: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch news items with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if country:
            clauses.append("country = ?")
            params.append(country)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM news_items{where} ORDER BY collected_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]

    def get_news_item(self, news_id: int) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM news_items WHERE id = ?", (news_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_news_status(self, news_id: int, status: str) -> None:
        self.conn.execute(
            "UPDATE news_items SET status = ? WHERE id = ?", (status, news_id)
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # articles CRUD
    # ------------------------------------------------------------------

    def insert_article(
        self,
        news_item_id: int,
        country: str,
        language: str,
        platform: str,
        title: str,
        body: str = "",
        caption: str = "",
        hashtags: str = "",
        has_fomus_mention: bool = False,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO articles
               (news_item_id, country, language, platform, title, body,
                caption, hashtags, has_fomus_mention, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                news_item_id,
                country,
                language,
                platform,
                title,
                body,
                caption,
                hashtags,
                int(has_fomus_mention),
                _now(),
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_articles(
        self,
        country: Optional[str] = None,
        status: Optional[str] = None,
        platform: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if country:
            clauses.append("country = ?")
            params.append(country)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM articles{where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]

    def get_article(self, article_id: int) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_article_status(self, article_id: int, status: str) -> None:
        self.conn.execute(
            "UPDATE articles SET status = ? WHERE id = ?", (status, article_id)
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # visual_assets CRUD
    # ------------------------------------------------------------------

    def insert_visual_asset(
        self,
        article_id: int,
        image_path: str,
        prompt_used: str = "",
        aspect_ratio: str = "1:1",
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO visual_assets
               (article_id, image_path, prompt_used, aspect_ratio, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (article_id, image_path, prompt_used, aspect_ratio, _now()),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_visual_assets(
        self,
        article_id: Optional[int] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if article_id is not None:
            rows = self.conn.execute(
                "SELECT * FROM visual_assets WHERE article_id = ? ORDER BY created_at DESC LIMIT ?",
                (article_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM visual_assets ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_visual_asset(self, asset_id: int) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM visual_assets WHERE id = ?", (asset_id,)
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # distribution_queue CRUD
    # ------------------------------------------------------------------

    def insert_distribution(
        self,
        article_id: int,
        visual_asset_id: int,
        platform: str,
        scheduled_time: str,
        tz: str = "",
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO distribution_queue
               (article_id, visual_asset_id, platform, scheduled_time, timezone)
               VALUES (?, ?, ?, ?, ?)""",
            (article_id, visual_asset_id, platform, scheduled_time, tz),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_distribution_queue(
        self,
        status: Optional[str] = None,
        platform: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM distribution_queue{where} ORDER BY scheduled_time ASC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]

    def update_distribution_status(
        self,
        dist_id: int,
        status: str,
        published_at: Optional[str] = None,
    ) -> None:
        if published_at:
            self.conn.execute(
                "UPDATE distribution_queue SET status = ?, published_at = ? WHERE id = ?",
                (status, published_at, dist_id),
            )
        else:
            self.conn.execute(
                "UPDATE distribution_queue SET status = ? WHERE id = ?",
                (status, dist_id),
            )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Status / statistics
    # ------------------------------------------------------------------

    def get_status_summary(self) -> dict[str, Any]:
        """Return a summary of counts by table and status."""
        summary: dict[str, Any] = {}

        for table, status_col in [
            ("news_items", "status"),
            ("articles", "status"),
            ("distribution_queue", "status"),
        ]:
            rows = self.conn.execute(
                f"SELECT {status_col}, COUNT(*) as cnt FROM {table} GROUP BY {status_col}"
            ).fetchall()
            summary[table] = {r["status"]: r["cnt"] for r in rows}  # type: ignore[index]

        asset_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM visual_assets"
        ).fetchone()
        summary["visual_assets"] = {"total": asset_count["cnt"] if asset_count else 0}  # type: ignore[index]

        return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
