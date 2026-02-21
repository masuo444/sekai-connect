"""TikTok Content Publishing API を使った自動投稿クライアント。

TikTok Developer Portal でアプリを作成し、Content Publishing API の
アクセス権を取得した上で利用する。

投稿フロー:
  - 画像投稿 (Photo Post): photo_images で URL 指定 -> Publish
  - 動画投稿: Init upload -> Upload video -> Publish

必要な環境変数:
  TIKTOK_ACCESS_TOKEN  -- OAuth2 で取得したアクセストークン
"""

import os
import logging
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = "https://open.tiktokapis.com/v2"


class TikTokClient:
    """TikTok Content Publishing API クライアント。

    環境変数 ``TIKTOK_ACCESS_TOKEN`` が設定されていない場合、
    ``enabled`` が ``False`` になり全ての投稿メソッドはスキップされる。
    """

    def __init__(self) -> None:
        self._access_token: str = os.getenv("TIKTOK_ACCESS_TOKEN", "")
        self._enabled: bool = bool(self._access_token)

        if not self._enabled:
            logger.warning(
                "TIKTOK_ACCESS_TOKEN が未設定のため TikTokClient は無効です"
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """トークンが設定済みで利用可能かどうかを返す。"""
        return self._enabled

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def publish_photo_post(
        self,
        image_urls: list[str],
        caption: str,
        privacy_level: str = "SELF_ONLY",
    ) -> dict[str, Any]:
        """画像投稿 (Photo Post) を行う。

        Args:
            image_urls: 画像 URL のリスト。TikTok が URL から画像を取得する。
            caption: 投稿のキャプション。
            privacy_level: 公開範囲。デフォルトは ``"SELF_ONLY"`` (非公開テスト)。
                選択肢: ``"SELF_ONLY"``, ``"MUTUAL_FOLLOW_FRIENDS"``,
                ``"FOLLOWER_OF_CREATOR"``, ``"PUBLIC_TO_EVERYONE"``

        Returns:
            API レスポンスの JSON dict。
        """
        if not self._enabled:
            logger.info("TikTokClient が無効のため publish_photo_post をスキップ")
            return {"skipped": True, "reason": "client_disabled"}

        payload: dict[str, Any] = {
            "post_info": {
                "title": caption,
                "privacy_level": privacy_level,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "photo_images": image_urls,
            },
            "media_type": "PHOTO",
        }

        return self._api_post(f"{BASE_URL}/post/publish/", payload)

    def publish_video(
        self,
        video_url: str,
        caption: str,
        privacy_level: str = "SELF_ONLY",
    ) -> dict[str, Any]:
        """動画投稿を行う。

        Args:
            video_url: 動画ファイルの URL。TikTok が URL から動画を取得する。
            caption: 投稿のキャプション。
            privacy_level: 公開範囲。デフォルトは ``"SELF_ONLY"`` (非公開テスト)。

        Returns:
            API レスポンスの JSON dict。
        """
        if not self._enabled:
            logger.info("TikTokClient が無効のため publish_video をスキップ")
            return {"skipped": True, "reason": "client_disabled"}

        payload: dict[str, Any] = {
            "post_info": {
                "title": caption,
                "privacy_level": privacy_level,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": video_url,
            },
            "media_type": "VIDEO",
        }

        return self._api_post(f"{BASE_URL}/post/publish/", payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """共通 API POST 呼び出し。

        Args:
            endpoint: リクエスト先の完全 URL。
            payload: リクエストボディに含める JSON dict。

        Returns:
            API レスポンスの JSON dict。

        Raises:
            httpx.HTTPStatusError: 4xx / 5xx レスポンス時。
        """
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
                logger.info("TikTok API 成功: %s -> %s", endpoint, data)
                return data
        except httpx.HTTPStatusError as exc:
            logger.error(
                "TikTok API HTTP エラー: %s %s - %s",
                exc.response.status_code,
                endpoint,
                exc.response.text,
            )
            raise
        except httpx.RequestError as exc:
            logger.error("TikTok API リクエストエラー: %s - %s", endpoint, exc)
            raise
