"""Instagram Graph API を使った自動投稿クライアント。

Instagram Graph API の仕組み:
- Facebook Page に紐づく Instagram Business/Creator アカウントが必要
- 投稿フロー: 1) メディアコンテナ作成 -> 2) 公開
- 必要な環境変数: INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ACCOUNT_ID
"""

import os
import logging
import httpx
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_URL = "https://graph.instagram.com/v21.0"


class InstagramClient:
    """Instagram Graph API クライアント。

    単一画像・カルーセル・リールの投稿をサポートする。
    環境変数が未設定の場合は enabled=False となり、投稿をスキップできる。
    """

    def __init__(self) -> None:
        """`.env` からアクセストークンとビジネスアカウント ID を読み込む。

        環境変数が未設定の場合は warning を出力し、enabled を False にする。
        """
        load_dotenv()

        self.access_token: str | None = os.getenv("INSTAGRAM_ACCESS_TOKEN")
        self.account_id: str | None = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")

        if not self.access_token or not self.account_id:
            logger.warning(
                "Instagram API の環境変数が未設定です "
                "(INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ACCOUNT_ID)。"
                "投稿機能は無効になります。"
            )
            self.enabled: bool = False
        else:
            self.enabled = True
            logger.info("InstagramClient を初期化しました (account_id=%s)", self.account_id)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def publish_image_post(self, image_url: str, caption: str) -> dict:
        """単一画像を投稿する。

        Args:
            image_url: 公開アクセス可能な画像の URL。
            caption: 投稿キャプション。

        Returns:
            公開された投稿の API レスポンス。

        Raises:
            RuntimeError: クライアントが無効 (enabled=False) の場合。
            httpx.HTTPStatusError: API 呼び出しに失敗した場合。
        """
        self._ensure_enabled()
        logger.info("単一画像投稿を開始します: image_url=%s", image_url)

        # Step 1: メディアコンテナ作成
        container = self._api_post(
            f"/{self.account_id}/media",
            params={
                "image_url": image_url,
                "caption": caption,
            },
        )
        container_id: str = container["id"]
        logger.info("メディアコンテナを作成しました: container_id=%s", container_id)

        # Step 2: 公開
        result = self._api_post(
            f"/{self.account_id}/media_publish",
            params={"creation_id": container_id},
        )
        logger.info("画像投稿を公開しました: %s", result)
        return result

    def publish_carousel(self, image_urls: list[str], caption: str) -> dict:
        """カルーセル (複数画像) 投稿を行う。

        Args:
            image_urls: 公開アクセス可能な画像 URL のリスト (2〜10 枚)。
            caption: 投稿キャプション。

        Returns:
            公開された投稿の API レスポンス。

        Raises:
            RuntimeError: クライアントが無効の場合。
            ValueError: 画像が 2 枚未満または 10 枚超の場合。
            httpx.HTTPStatusError: API 呼び出しに失敗した場合。
        """
        self._ensure_enabled()

        if len(image_urls) < 2:
            raise ValueError("カルーセル投稿には 2 枚以上の画像が必要です。")
        if len(image_urls) > 10:
            raise ValueError("カルーセル投稿は最大 10 枚までです。")

        logger.info("カルーセル投稿を開始します: %d 枚の画像", len(image_urls))

        # 各画像の子コンテナを作成
        children_ids: list[str] = []
        for i, url in enumerate(image_urls):
            child = self._api_post(
                f"/{self.account_id}/media",
                params={
                    "image_url": url,
                    "is_carousel_item": "true",
                },
            )
            children_ids.append(child["id"])
            logger.info("子コンテナ %d/%d を作成: id=%s", i + 1, len(image_urls), child["id"])

        # カルーセルコンテナを作成
        carousel = self._api_post(
            f"/{self.account_id}/media",
            params={
                "media_type": "CAROUSEL",
                "children": ",".join(children_ids),
                "caption": caption,
            },
        )
        carousel_id: str = carousel["id"]
        logger.info("カルーセルコンテナを作成しました: carousel_id=%s", carousel_id)

        # 公開
        result = self._api_post(
            f"/{self.account_id}/media_publish",
            params={"creation_id": carousel_id},
        )
        logger.info("カルーセル投稿を公開しました: %s", result)
        return result

    def publish_reel(self, video_url: str, caption: str) -> dict:
        """リール (短尺動画) を投稿する。

        Args:
            video_url: 公開アクセス可能な動画の URL。
            caption: 投稿キャプション。

        Returns:
            公開された投稿の API レスポンス。

        Raises:
            RuntimeError: クライアントが無効の場合。
            httpx.HTTPStatusError: API 呼び出しに失敗した場合。
        """
        self._ensure_enabled()
        logger.info("リール投稿を開始します: video_url=%s", video_url)

        # Step 1: メディアコンテナ作成 (media_type=REELS)
        container = self._api_post(
            f"/{self.account_id}/media",
            params={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
            },
        )
        container_id: str = container["id"]
        logger.info("リールコンテナを作成しました: container_id=%s", container_id)

        # Step 2: 公開
        result = self._api_post(
            f"/{self.account_id}/media_publish",
            params={"creation_id": container_id},
        )
        logger.info("リール投稿を公開しました: %s", result)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _api_post(self, endpoint: str, params: dict) -> dict:
        """Instagram Graph API への POST リクエストを実行する。

        Args:
            endpoint: API エンドポイントパス (例: ``/{account_id}/media``)。
            params: リクエストパラメータ。access_token は自動付与される。

        Returns:
            API レスポンスの JSON dict。

        Raises:
            httpx.HTTPStatusError: レスポンスがエラーステータスの場合。
        """
        url = f"{BASE_URL}{endpoint}"
        params_with_token = {**params, "access_token": self.access_token}

        logger.debug("API POST: %s params=%s", url, {k: v for k, v in params.items()})

        response = httpx.post(url, params=params_with_token)

        # エラーハンドリング
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.error(
                "Instagram API エラー: status=%d body=%s",
                response.status_code,
                response.text,
            )
            raise

        data: dict = response.json()
        logger.debug("API レスポンス: %s", data)
        return data

    def _ensure_enabled(self) -> None:
        """クライアントが有効であることを確認する。無効なら RuntimeError を送出。"""
        if not self.enabled:
            raise RuntimeError(
                "InstagramClient は無効です。環境変数を設定してください: "
                "INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ACCOUNT_ID"
            )
