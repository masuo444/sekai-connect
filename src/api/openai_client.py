"""OpenAI GPT-5.2 API wrapper for Connect-Sekai content generation."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

load_dotenv()
logger = logging.getLogger(__name__)


class OpenAIClient:
    """OpenAI API client for article, SNS caption, and translation tasks."""

    def __init__(self, model: str = "gpt-5.2") -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set in .env")
        self.client = OpenAI(api_key=api_key)
        self.model = model

    # ------------------------------------------------------------------
    # Article generation
    # ------------------------------------------------------------------

    def generate_article(
        self,
        topic: str,
        tone: str,
        language: str = "ja",
        system_prompt: str = "",
        max_completion_tokens: int = 2000,
    ) -> dict[str, Any]:
        """Generate a long-form article with country-specific tone.

        Args:
            topic: The article subject or news summary.
            tone: One of 'investment-luxury', 'culture-business', 'royal-tradition'.
            language: Target language code ('ja', 'en', 'ar').
            system_prompt: Optional system prompt override.
            max_completion_tokens: Maximum response length.

        Returns:
            dict with 'title', 'body', 'hashtags' keys.
        """
        lang_label = {"ja": "日本語", "en": "English", "ar": "العربية"}.get(
            language, language
        )
        default_system = (
            f"You are an elite content writer for Connect-Sekai, producing sophisticated "
            f"media content with a '{tone}' tone. Write in {lang_label}. "
            f"Your writing is intellectual, refined, and conveys exclusivity."
        )
        messages = [
            {"role": "system", "content": system_prompt or default_system},
            {
                "role": "user",
                "content": (
                    f"以下のトピックについて記事を生成してください。\n\n"
                    f"トピック: {topic}\n"
                    f"トーン: {tone}\n"
                    f"言語: {lang_label}\n\n"
                    f"出力形式 (JSONのみ):\n"
                    f'{{"title": "記事タイトル", '
                    f'"body": "記事本文(HTML不要、プレーンテキスト)", '
                    f'"hashtags": ["タグ1", "タグ2"]}}'
                ),
            },
        ]
        return self._call_json(messages, max_completion_tokens=max_completion_tokens, fallback={
            "title": topic,
            "body": "",
            "hashtags": [],
        })

    # ------------------------------------------------------------------
    # SNS caption generation
    # ------------------------------------------------------------------

    def generate_sns_caption(
        self,
        topic: str,
        platform: str,
        tone: str,
        language: str = "ja",
        hashtags: list[str] | None = None,
        system_prompt: str = "",
    ) -> dict[str, Any]:
        """Generate a platform-specific SNS caption.

        Args:
            topic: The content subject or article summary.
            platform: One of 'instagram', 'x', 'tiktok'.
            tone: Country tone identifier.
            language: Target language code.
            hashtags: Suggested hashtags to include.
            system_prompt: Optional system prompt override.

        Returns:
            dict with platform-specific content fields.
        """
        platform_rules = {
            "instagram": (
                "Instagramカルーセル投稿向け。長めのキャプション（500-800字）で読み応えのある内容。"
                "改行を効果的に使い、ハッシュタグを末尾にまとめる。"
            ),
            "x": (
                "X (Twitter) 向け。280字以内の鋭く知的なポスト。"
                "インサイトを凝縮し、続きが気になる構成に。ハッシュタグは最大3個。"
            ),
            "tiktok": (
                "TikTok動画向けナレーション台本。15-60秒で読めるテンポの良い構成。"
                "フック→本題→CTA の流れで。話し言葉で親しみやすく。"
            ),
        }
        rule = platform_rules.get(platform, platform_rules["instagram"])
        hashtag_str = " ".join(hashtags) if hashtags else ""

        default_system = (
            f"You are a social media specialist for Connect-Sekai. "
            f"Tone: '{tone}'. Produce refined, exclusive content."
        )

        output_spec = {
            "instagram": (
                '{"caption": "キャプション本文", "hashtags": ["#tag1", "#tag2"], '
                '"carousel_slides": ["スライド1テキスト", "スライド2テキスト"]}'
            ),
            "x": '{"post": "280字以内のポスト", "hashtags": ["#tag1"]}',
            "tiktok": (
                '{"hook": "冒頭フック(3秒)", "narration": "ナレーション本文", '
                '"cta": "CTA文言"}'
            ),
        }

        messages = [
            {"role": "system", "content": system_prompt or default_system},
            {
                "role": "user",
                "content": (
                    f"以下のトピックからSNS投稿を作成してください。\n\n"
                    f"トピック: {topic}\n"
                    f"プラットフォーム: {platform}\n"
                    f"ルール: {rule}\n"
                    f"推奨ハッシュタグ: {hashtag_str}\n"
                    f"言語: {language}\n\n"
                    f"出力形式 (JSONのみ):\n{output_spec.get(platform, output_spec['instagram'])}"
                ),
            },
        ]

        fallbacks = {
            "instagram": {"caption": topic, "hashtags": hashtags or [], "carousel_slides": []},
            "x": {"post": topic[:280], "hashtags": hashtags or []},
            "tiktok": {"hook": "", "narration": topic, "cta": ""},
        }
        return self._call_json(
            messages,
            max_completion_tokens=1500,
            fallback=fallbacks.get(platform, fallbacks["instagram"]),
        )

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def translate(
        self,
        text: str,
        target_language: str,
        context: str = "",
    ) -> dict[str, str]:
        """Translate text while preserving tone and nuance.

        Args:
            text: Source text to translate.
            target_language: Target language code ('ja', 'en', 'ar').
            context: Additional context for translation accuracy.

        Returns:
            dict with 'translated_text' and 'target_language' keys.
        """
        lang_map = {"ja": "日本語", "en": "English", "ar": "العربية"}
        lang_label = lang_map.get(target_language, target_language)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a professional translator for Connect-Sekai. "
                    "Maintain the sophisticated, intellectual tone of the original. "
                    "Preserve brand terms and proper nouns."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"以下のテキストを{lang_label}に翻訳してください。\n\n"
                    f"原文:\n{text}\n\n"
                    f"{'コンテキスト: ' + context if context else ''}\n\n"
                    f"出力形式 (JSONのみ):\n"
                    f'{{"translated_text": "翻訳文", "target_language": "{target_language}"}}'
                ),
            },
        ]
        return self._call_json(messages, max_completion_tokens=2000, fallback={
            "translated_text": text,
            "target_language": target_language,
        })

    # ------------------------------------------------------------------
    # Hashtag optimization
    # ------------------------------------------------------------------

    def optimize_hashtags(
        self,
        topic: str,
        platform: str,
        base_hashtags: list[str],
        language: str = "ja",
        max_count: int = 15,
    ) -> list[str]:
        """Optimize and expand hashtags for maximum reach.

        Args:
            topic: The content topic for context.
            platform: Target platform ('instagram', 'x', 'tiktok').
            base_hashtags: Seed hashtags from country config.
            language: Target language code.
            max_count: Maximum number of hashtags to return.

        Returns:
            Optimized list of hashtags.
        """
        platform_limits = {"instagram": 30, "x": 3, "tiktok": 8}
        limit = min(max_count, platform_limits.get(platform, max_count))

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a social media hashtag strategist for Connect-Sekai. "
                    "Optimize hashtags for maximum organic reach among affluent audiences."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"以下の条件でハッシュタグを最適化してください。\n\n"
                    f"トピック: {topic}\n"
                    f"プラットフォーム: {platform}\n"
                    f"ベースタグ: {', '.join(base_hashtags)}\n"
                    f"言語: {language}\n"
                    f"最大数: {limit}\n\n"
                    f"要件:\n"
                    f"- ベースタグを含めつつ、関連性の高いタグを追加\n"
                    f"- 富裕層・投資家層にリーチするニッチタグを混ぜる\n"
                    f"- ボリュームの大きいタグと小さいタグをバランスよく\n\n"
                    f"出力形式 (JSONのみ):\n"
                    f'{{"hashtags": ["#tag1", "#tag2"]}}'
                ),
            },
        ]
        result = self._call_json(messages, max_completion_tokens=500, fallback={
            "hashtags": base_hashtags[:limit],
        })
        return result.get("hashtags", base_hashtags[:limit])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_json(
        self,
        messages: list[dict[str, str]],
        max_completion_tokens: int = 4000,
        fallback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request and parse the JSON response."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=max_completion_tokens,
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content or ""
            text = text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                # Remove opening fence (```json or ```)
                first_newline = text.find("\n")
                text = text[first_newline + 1:] if first_newline != -1 else text[3:]
                # Remove closing fence
                if text.rstrip().endswith("```"):
                    text = text.rstrip()[:-3]
                text = text.strip()
            # Try to extract JSON object from response
            if not text.startswith("{"):
                start = text.find("{")
                if start != -1:
                    # Find matching closing brace
                    depth = 0
                    for idx in range(start, len(text)):
                        if text[idx] == "{":
                            depth += 1
                        elif text[idx] == "}":
                            depth -= 1
                            if depth == 0:
                                text = text[start:idx + 1]
                                break
            return json.loads(text)
        except (OpenAIError, json.JSONDecodeError) as e:
            logger.warning("OpenAI API call failed: %s", e)
            return fallback if fallback is not None else {}
