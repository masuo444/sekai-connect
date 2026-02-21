"""Google Gemini API wrapper for Connect-Sekai."""

from __future__ import annotations

import os
import logging
from typing import Any

from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
logger = logging.getLogger(__name__)


class GeminiClient:
    """Gemini API client for news analysis and scoring."""

    def __init__(self, model_name: str = "gemini-2.5-flash") -> None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY is not set in .env")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)

    def summarize_article(self, title: str, description: str, country_key: str) -> dict[str, Any]:
        """Summarize a news article and extract key points."""
        prompt = (
            f"以下のニュース記事を日本語で簡潔に要約し、JSON形式で返してください。\n"
            f"国/地域: {country_key}\n"
            f"タイトル: {title}\n"
            f"概要: {description}\n\n"
            f"出力形式 (JSONのみ、マークダウン不要):\n"
            f'{{"summary": "日本語の要約(100字以内)", '
            f'"key_topics": ["トピック1", "トピック2"], '
            f'"relevance": "日本の投資家・経営者との関連性を1文で"}}'
        )
        return self._call_json(prompt, fallback={
            "summary": f"{title} ({country_key}関連ニュース)",
            "key_topics": [],
            "relevance": "分析不可",
        })

    def score_for_investors(
        self, title: str, summary: str, country_key: str, tone: str, topics: list[str]
    ) -> dict[str, Any]:
        """Score how appealing an article is for Japanese investors/executives."""
        prompt = (
            f"以下のニュース記事を「日本人経営者・投資家にどれだけ刺さるか」で評価してください。\n\n"
            f"国: {country_key}\n"
            f"ブランドトーン: {tone}\n"
            f"対象トピック: {', '.join(topics)}\n"
            f"タイトル: {title}\n"
            f"要約: {summary}\n\n"
            f"出力形式 (JSONのみ、マークダウン不要):\n"
            f'{{"score": 0-100の整数, '
            f'"reason": "スコアの理由(1文)", '
            f'"angle": "日本人投資家向けの切り口提案(1文)", '
            f'"content_type": "investment|lifestyle|culture|business のいずれか"}}'
        )
        return self._call_json(prompt, fallback={
            "score": 50,
            "reason": "API分析不可のためデフォルトスコア",
            "angle": title,
            "content_type": "business",
        })

    def _call_json(self, prompt: str, fallback: dict[str, Any]) -> dict[str, Any]:
        """Call Gemini and parse JSON response, with fallback on failure."""
        try:
            response = self.model.generate_content(prompt)
            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            import json
            return json.loads(text)
        except Exception as e:
            logger.warning("Gemini API call failed: %s", e)
            return fallback
