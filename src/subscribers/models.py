"""購読者データベース管理 for Connect-Sekai."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = _ROOT / "data" / "connect_nexus.db"

# HMAC secret for unsubscribe tokens — override via env var in production.
HMAC_SECRET = os.getenv("NEWSLETTER_HMAC_SECRET", "connect-sekai-default-secret-change-me")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SUBSCRIBERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    email            TEXT    NOT NULL UNIQUE,
    name             TEXT    DEFAULT '',
    subscribed_at    TEXT    NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'unsubscribed')),
    source           TEXT    NOT NULL DEFAULT 'web'
        CHECK (source IN ('web', 'whatsapp')),
    unsubscribe_token TEXT   NOT NULL
);

CREATE TABLE IF NOT EXISTS newsletter_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    subscriber_id    INTEGER REFERENCES subscribers(id),
    sent_at          TEXT    NOT NULL,
    subject          TEXT    NOT NULL,
    article_count    INTEGER DEFAULT 0,
    status           TEXT    NOT NULL DEFAULT 'sent'
        CHECK (status IN ('sent', 'failed'))
);
"""


def generate_unsubscribe_token(email: str) -> str:
    """HMACベースの購読解除トークンを生成する。"""
    return hmac.new(
        HMAC_SECRET.encode(),
        email.lower().encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_unsubscribe_token(email: str, token: str) -> bool:
    """購読解除トークンを検証する。"""
    expected = generate_unsubscribe_token(email)
    return hmac.compare_digest(expected, token)


class SubscriberDatabase:
    """購読者テーブルの管理クラス。"""

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
        """購読者テーブルを作成する。"""
        self.conn.executescript(_SUBSCRIBERS_SCHEMA)
        self.conn.commit()
        logger.info("Subscribers table initialized at %s", self.db_path)

    # ------------------------------------------------------------------
    # Subscriber CRUD
    # ------------------------------------------------------------------

    def add_subscriber(
        self,
        email: str,
        name: str = "",
        source: str = "web",
    ) -> int:
        """新しい購読者を追加して id を返す。

        既にアクティブな購読者が存在する場合は -1 を返す。
        過去に購読解除した場合は再アクティブ化する。
        """
        email = email.lower().strip()
        token = generate_unsubscribe_token(email)

        existing = self.get_subscriber_by_email(email)
        if existing:
            if existing["status"] == "active":
                return -1  # duplicate
            # 再購読: status を active に戻す
            self.conn.execute(
                "UPDATE subscribers SET status = 'active', name = ?, source = ?, unsubscribe_token = ? WHERE id = ?",
                (name, source, token, existing["id"]),
            )
            self.conn.commit()
            logger.info("Re-activated subscriber: %s", email)
            return existing["id"]

        cur = self.conn.execute(
            """INSERT INTO subscribers
               (email, name, subscribed_at, status, source, unsubscribe_token)
               VALUES (?, ?, ?, 'active', ?, ?)""",
            (email, name, _now(), source, token),
        )
        self.conn.commit()
        logger.info("Added new subscriber: %s", email)
        return cur.lastrowid  # type: ignore[return-value]

    def get_subscriber_by_email(self, email: str) -> Optional[dict[str, Any]]:
        """メールアドレスで購読者を検索する。"""
        row = self.conn.execute(
            "SELECT * FROM subscribers WHERE email = ?", (email.lower().strip(),)
        ).fetchone()
        return dict(row) if row else None

    def get_active_subscribers(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """アクティブな購読者一覧を取得する。"""
        rows = self.conn.execute(
            "SELECT * FROM subscribers WHERE status = 'active' ORDER BY subscribed_at ASC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_active_subscribers(self) -> int:
        """アクティブな購読者数を返す。"""
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM subscribers WHERE status = 'active'"
        ).fetchone()
        return row["cnt"] if row else 0

    def unsubscribe(self, email: str, token: str) -> bool:
        """購読を解除する。トークン検証に成功した場合は True を返す。"""
        email = email.lower().strip()
        if not verify_unsubscribe_token(email, token):
            return False

        self.conn.execute(
            "UPDATE subscribers SET status = 'unsubscribed' WHERE email = ?",
            (email,),
        )
        self.conn.commit()
        logger.info("Unsubscribed: %s", email)
        return True

    # ------------------------------------------------------------------
    # Newsletter log
    # ------------------------------------------------------------------

    def log_newsletter_sent(
        self,
        subscriber_id: int,
        subject: str,
        article_count: int,
        status: str = "sent",
    ) -> int:
        """ニュースレター送信ログを記録する。"""
        cur = self.conn.execute(
            """INSERT INTO newsletter_log
               (subscriber_id, sent_at, subject, article_count, status)
               VALUES (?, ?, ?, ?, ?)""",
            (subscriber_id, _now(), subject, article_count, status),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def was_newsletter_sent_today(self, subscriber_id: int) -> bool:
        """本日すでにニュースレターを送信済みか確認する。"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = self.conn.execute(
            """SELECT COUNT(*) as cnt FROM newsletter_log
               WHERE subscriber_id = ? AND sent_at LIKE ? AND status = 'sent'""",
            (subscriber_id, f"{today}%"),
        ).fetchone()
        return (row["cnt"] if row else 0) > 0

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_subscriber_stats(self) -> dict[str, int]:
        """購読者の統計情報を返す。"""
        stats: dict[str, int] = {}
        for status in ("active", "unsubscribed"):
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM subscribers WHERE status = ?",
                (status,),
            ).fetchone()
            stats[status] = row["cnt"] if row else 0
        return stats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
