"""Connect-Sekai ニュースレター購読 API。

軽量な FastAPI アプリケーション。
実行方法: python -m src.subscribers.api
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, field_validator

# .env をプロジェクトルートから読み込み
_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_ROOT / ".env")

from src.subscribers.models import SubscriberDatabase

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Connect-Sekai Newsletter API",
    docs_url=None,
    redoc_url=None,
)

# CORS — 同一ドメインからのリクエストを許可
ALLOWED_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "https://connect-sekai.com,http://connect-sekai.com,http://localhost,http://127.0.0.1",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

_db: SubscriberDatabase | None = None


def get_db() -> SubscriberDatabase:
    global _db
    if _db is None:
        _db = SubscriberDatabase()
        _db.init_db()
    return _db


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


class SubscribeRequest(BaseModel):
    email: str
    name: str = ""
    source: str = "web"

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("有効なメールアドレスを入力してください")
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        if v not in ("web", "whatsapp"):
            return "web"
        return v


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/subscribe")
async def subscribe(req: SubscribeRequest) -> JSONResponse:
    """メールアドレスを登録して購読を開始する。"""
    db = get_db()
    result = db.add_subscriber(
        email=req.email,
        name=req.name,
        source=req.source,
    )

    if result == -1:
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "message": "このメールアドレスはすでに登録されています",
            },
        )

    logger.info("New subscriber: %s (source=%s)", req.email, req.source)
    return JSONResponse(
        status_code=201,
        content={
            "success": True,
            "message": "購読登録が完了しました。最新ニュースをお届けします！",
        },
    )


@app.get("/api/unsubscribe")
async def unsubscribe(
    email: str = Query(..., description="購読者のメールアドレス"),
    token: str = Query(..., description="購読解除トークン"),
) -> HTMLResponse:
    """購読を解除する。"""
    db = get_db()
    success = db.unsubscribe(email=email, token=token)

    if success:
        html = _unsubscribe_html(
            title="購読解除完了",
            message="購読解除しました。ご利用ありがとうございました。",
            success=True,
        )
    else:
        html = _unsubscribe_html(
            title="エラー",
            message="購読解除に失敗しました。リンクが無効か、すでに解除済みです。",
            success=False,
        )

    return HTMLResponse(content=html)


@app.get("/api/health")
async def health() -> JSONResponse:
    """ヘルスチェック。"""
    db = get_db()
    stats = db.get_subscriber_stats()
    return JSONResponse(content={"status": "ok", "subscribers": stats})


# ---------------------------------------------------------------------------
# HTML template for unsubscribe page
# ---------------------------------------------------------------------------

def _unsubscribe_html(title: str, message: str, success: bool) -> str:
    color = "#1A6B4F" if success else "#BC002D"
    icon = "&#10003;" if success else "&#10007;"
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} | Connect-Sekai</title>
    <style>
        body {{
            font-family: 'Noto Sans JP', sans-serif;
            background: #F5F0E8;
            color: #1B2A4A;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
        }}
        .card {{
            background: #fff;
            border-radius: 8px;
            padding: 3rem 2rem;
            text-align: center;
            max-width: 480px;
            box-shadow: 0 4px 16px rgba(27,42,74,0.1);
        }}
        .icon {{
            font-size: 3rem;
            color: {color};
            margin-bottom: 1rem;
        }}
        h1 {{
            font-size: 1.5rem;
            margin-bottom: 1rem;
        }}
        p {{
            color: #6B7280;
            line-height: 1.7;
        }}
        a {{
            display: inline-block;
            margin-top: 1.5rem;
            color: #C9A84C;
            text-decoration: none;
            font-weight: 500;
        }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">{icon}</div>
        <h1>{title}</h1>
        <p>{message}</p>
        <a href="https://connect-sekai.com">Connect-Sekai トップページへ</a>
    </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Standalone execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8001"))

    logger.info("Starting Newsletter API on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port)
