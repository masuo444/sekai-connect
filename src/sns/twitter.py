"""X (Twitter) API v2 を使った自動投稿クライアント。

X API v2 の仕組み:
- OAuth 2.0 Bearer Token または OAuth 1.0a User Context が必要
- ツイート投稿: POST https://api.x.com/2/tweets
- 画像付きツイート: まずメディアアップロード (v1.1 endpoint) -> tweet に media_ids 添付
- 必要な環境変数: TWITTER_BEARER_TOKEN, TWITTER_API_KEY, TWITTER_API_SECRET,
  TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET

注意: X API 無料プラン (Free tier) は月 1,500 ツイートまで。
"""

import base64
import hashlib
import hmac
import logging
import os
import time
import uuid
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

TWEETS_ENDPOINT = "https://api.x.com/2/tweets"
MEDIA_UPLOAD_ENDPOINT = "https://upload.twitter.com/1.1/media/upload.json"


class TwitterClient:
    """X (Twitter) API v2 クライアント。

    OAuth 1.0a User Context を使ってツイート投稿・画像付き投稿を行う。
    環境変数が未設定の場合は ``enabled=False`` となり、投稿をスキップできる。

    無料プランでは月 1,500 ツイートの制限があるため、
    投稿ごとにログを出力して利用状況を把握しやすくしている。
    """

    def __init__(self) -> None:
        """`.env` から API キー群を読み込む。

        必要な環境変数が 1 つでも未設定の場合は warning を出力し、
        ``enabled`` を ``False`` にする。
        """
        load_dotenv()

        self._api_key: str = os.getenv("TWITTER_API_KEY", "")
        self._api_secret: str = os.getenv("TWITTER_API_SECRET", "")
        self._access_token: str = os.getenv("TWITTER_ACCESS_TOKEN", "")
        self._access_secret: str = os.getenv("TWITTER_ACCESS_SECRET", "")
        self._bearer_token: str = os.getenv("TWITTER_BEARER_TOKEN", "")

        # OAuth 1.0a に必要な 4 つのキーが揃っているかチェック
        required = {
            "TWITTER_API_KEY": self._api_key,
            "TWITTER_API_SECRET": self._api_secret,
            "TWITTER_ACCESS_TOKEN": self._access_token,
            "TWITTER_ACCESS_SECRET": self._access_secret,
        }
        missing = [k for k, v in required.items() if not v]

        if missing:
            logger.warning(
                "X (Twitter) API の環境変数が未設定です (%s)。"
                "投稿機能は無効になります。",
                ", ".join(missing),
            )
            self._enabled: bool = False
        else:
            self._enabled = True
            logger.info(
                "TwitterClient を初期化しました "
                "(無料プラン: 月 1,500 ツイート上限に注意)"
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """API キーが設定済みで利用可能かどうかを返す。"""
        return self._enabled

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def publish_text_post(self, text: str) -> dict[str, Any]:
        """テキストのみのツイートを投稿する。

        Args:
            text: ツイート本文 (最大 280 文字)。

        Returns:
            API レスポンスの JSON dict。

        Raises:
            RuntimeError: クライアントが無効 (enabled=False) の場合。
            httpx.HTTPStatusError: API 呼び出しに失敗した場合。
        """
        self._ensure_enabled()
        logger.info("テキスト投稿を開始します (文字数: %d)", len(text))

        url = TWEETS_ENDPOINT
        payload: dict[str, Any] = {"text": text}
        headers = self._oauth_headers("POST", url)
        headers["Content-Type"] = "application/json"

        result = self._api_post(url, headers=headers, payload=payload)
        logger.info(
            "テキスト投稿が完了しました: tweet_id=%s "
            "(無料プラン月間上限 1,500 に注意)",
            result.get("data", {}).get("id", "unknown"),
        )
        return result

    def publish_image_post(self, text: str, image_path: str) -> dict[str, Any]:
        """画像付きツイートを投稿する。

        Step 1: v1.1 メディアアップロード API で画像をアップロードし media_id を取得。
        Step 2: v2 ツイート API に media_ids を添付して投稿。

        Args:
            text: ツイート本文。
            image_path: アップロードする画像のローカルファイルパス。

        Returns:
            API レスポンスの JSON dict。

        Raises:
            RuntimeError: クライアントが無効の場合。
            FileNotFoundError: 画像ファイルが存在しない場合。
            httpx.HTTPStatusError: API 呼び出しに失敗した場合。
        """
        self._ensure_enabled()

        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"画像ファイルが見つかりません: {image_path}")

        logger.info(
            "画像付き投稿を開始します: image_path=%s (文字数: %d)",
            image_path,
            len(text),
        )

        # Step 1: メディアアップロード (v1.1 endpoint, multipart/form-data)
        media_id = self._upload_media(image_path)
        logger.info("メディアアップロード完了: media_id=%s", media_id)

        # Step 2: ツイート投稿 (v2 endpoint)
        url = TWEETS_ENDPOINT
        payload: dict[str, Any] = {
            "text": text,
            "media": {"media_ids": [media_id]},
        }
        headers = self._oauth_headers("POST", url)
        headers["Content-Type"] = "application/json"

        result = self._api_post(url, headers=headers, payload=payload)
        logger.info(
            "画像付き投稿が完了しました: tweet_id=%s "
            "(無料プラン月間上限 1,500 に注意)",
            result.get("data", {}).get("id", "unknown"),
        )
        return result

    # ------------------------------------------------------------------
    # OAuth 1.0a signature
    # ------------------------------------------------------------------

    def _oauth_headers(
        self,
        method: str,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """OAuth 1.0a HMAC-SHA1 署名を生成し Authorization ヘッダーを返す。

        標準ライブラリのみで実装している (hmac, hashlib, base64, urllib.parse,
        time, uuid)。外部ライブラリ (requests-oauthlib 等) は使わない。

        Args:
            method: HTTP メソッド (``"GET"`` / ``"POST"`` 等)。
            url: リクエスト先の完全 URL。
            params: 追加のリクエストパラメータ (クエリ文字列やフォーム)。

        Returns:
            ``Authorization`` ヘッダーを含む dict。
        """
        oauth_params: dict[str, str] = {
            "oauth_consumer_key": self._api_key,
            "oauth_token": self._access_token,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_nonce": uuid.uuid4().hex,
            "oauth_version": "1.0",
        }

        # 署名ベース文字列に含める全パラメータ
        all_params: dict[str, str] = {**oauth_params}
        if params:
            all_params.update(params)

        # パラメータをソートしてエンコード
        sorted_params = sorted(all_params.items())
        param_string = urlencode(sorted_params, quote_via=quote)

        # 署名ベース文字列: METHOD&URL&PARAMS
        base_string = "&".join(
            [
                method.upper(),
                quote(url, safe=""),
                quote(param_string, safe=""),
            ]
        )

        # 署名キー: consumer_secret&token_secret
        signing_key = f"{quote(self._api_secret, safe='')}&{quote(self._access_secret, safe='')}"

        # HMAC-SHA1 署名
        hashed = hmac.new(
            signing_key.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha1,
        )
        signature = base64.b64encode(hashed.digest()).decode("utf-8")

        oauth_params["oauth_signature"] = signature

        # Authorization ヘッダー組み立て
        auth_header = "OAuth " + ", ".join(
            f'{quote(k, safe="")}="{quote(v, safe="")}"'
            for k, v in sorted(oauth_params.items())
        )

        return {"Authorization": auth_header}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _upload_media(self, image_path: str) -> str:
        """v1.1 メディアアップロード API で画像をアップロードする。

        Args:
            image_path: アップロードする画像のローカルファイルパス。

        Returns:
            アップロードされたメディアの ``media_id_string``。

        Raises:
            httpx.HTTPStatusError: アップロードに失敗した場合。
        """
        url = MEDIA_UPLOAD_ENDPOINT

        # multipart upload には OAuth パラメータのみで署名 (ファイルは含めない)
        headers = self._oauth_headers("POST", url)

        with open(image_path, "rb") as f:
            files = {"media_data": (os.path.basename(image_path), f)}
            result = self._api_post(url, headers=headers, files=files)

        media_id: str = result["media_id_string"]
        return media_id

    def _api_post(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """共通 API POST 呼び出し。

        JSON ボディまたは multipart/form-data (ファイルアップロード) に対応する。

        Args:
            url: リクエスト先の完全 URL。
            headers: リクエストヘッダー。
            payload: JSON リクエストボディ (ツイート投稿時)。
            files: multipart/form-data で送信するファイル (メディアアップロード時)。

        Returns:
            API レスポンスの JSON dict。

        Raises:
            httpx.HTTPStatusError: 4xx / 5xx レスポンス時。
        """
        try:
            with httpx.Client(timeout=60.0) as client:
                if files is not None:
                    # multipart/form-data (メディアアップロード)
                    response = client.post(url, headers=headers, files=files)
                else:
                    # JSON ボディ (ツイート投稿)
                    response = client.post(url, headers=headers, json=payload)

                response.raise_for_status()
                data: dict[str, Any] = response.json()
                logger.debug("X API レスポンス: %s -> %s", url, data)
                return data

        except httpx.HTTPStatusError as exc:
            logger.error(
                "X API HTTP エラー: status=%d url=%s body=%s",
                exc.response.status_code,
                url,
                exc.response.text,
            )
            raise
        except httpx.RequestError as exc:
            logger.error("X API リクエストエラー: url=%s error=%s", url, exc)
            raise

    def _ensure_enabled(self) -> None:
        """クライアントが有効であることを確認する。無効なら RuntimeError を送出。"""
        if not self._enabled:
            raise RuntimeError(
                "TwitterClient は無効です。環境変数を設定してください: "
                "TWITTER_API_KEY, TWITTER_API_SECRET, "
                "TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET"
            )
