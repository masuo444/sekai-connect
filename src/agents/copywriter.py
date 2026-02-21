"""Content generation agent for Connect-Sekai.

Takes analyzed news data from TrendAnalyst and produces platform-specific
content with country-appropriate tone and optional FOMUS stealth branding.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from src.api.openai_client import OpenAIClient
from src.content.prompts.system_prompts import (
    COPYWRITER_AR_PROMPT,
    COPYWRITER_EN_PROMPT,
    COPYWRITER_JA_PROMPT,
    FOMUS_STEALTH_PROMPT,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = _PROJECT_ROOT / "config" / "countries.yaml"

PLATFORM_LIST = ("instagram", "x", "tiktok")
TEMPLATES_DIR = _PROJECT_ROOT / "src" / "content" / "templates"

LANGUAGE_PROMPTS: dict[str, str] = {
    "ja": COPYWRITER_JA_PROMPT,
    "en": COPYWRITER_EN_PROMPT,
    "ar": COPYWRITER_AR_PROMPT,
}


class Copywriter:
    """Generates SNS-ready content from analyzed news articles."""

    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        with open(config_path, "r", encoding="utf-8") as f:
            self.config: dict[str, Any] = yaml.safe_load(f)
        self.countries: dict[str, dict[str, Any]] = self.config.get("countries", {})
        self.fomus_config: dict[str, Any] = self.config.get("fomus", {})
        self.openai = OpenAIClient()
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=True,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_all(
        self,
        news_data: dict[str, list[dict[str, Any]]],
        platforms: tuple[str, ...] = PLATFORM_LIST,
        languages: tuple[str, ...] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Generate content for all countries and platforms.

        Args:
            news_data: Output from TrendAnalyst.collect_all().
                       Mapping of country_key -> list of scored article dicts.
            platforms: Platforms to generate for.
            languages: Override per-country language list.

        Returns:
            Mapping of country_key -> list of generated content dicts.
        """
        results: dict[str, list[dict[str, Any]]] = {}
        for country_key, articles in news_data.items():
            country_cfg = self.countries.get(country_key)
            if not country_cfg:
                logger.warning("No config for country '%s', skipping", country_key)
                continue
            results[country_key] = self._generate_country(
                country_key, country_cfg, articles, platforms, languages
            )
        return results

    def generate_for_article(
        self,
        article: dict[str, Any],
        country_key: str,
        platforms: tuple[str, ...] = PLATFORM_LIST,
        languages: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate multi-platform content for a single article.

        Args:
            article: A single scored article dict from TrendAnalyst.
            country_key: Country identifier.
            platforms: Target platforms.
            languages: Override language list.

        Returns:
            List of content dicts, one per (platform, language) combination.
        """
        country_cfg = self.countries.get(country_key)
        if not country_cfg:
            raise ValueError(f"Unknown country: {country_key}")
        return self._generate_for_single_article(
            article, country_key, country_cfg, platforms, languages
        )

    def render_article(
        self,
        article_data: dict[str, Any],
        country_key: str,
        language: str = "ja",
    ) -> str:
        """Render a generated article through a Jinja2 template.

        Args:
            article_data: dict with 'title', 'body', 'hashtags' from OpenAI.
            country_key: Country identifier for template context.
            language: Language code to select the template.

        Returns:
            Rendered HTML string.
        """
        template_name = f"article_{language}.html.j2"
        template = self.jinja_env.get_template(template_name)
        country_cfg = self.countries.get(country_key, {})

        body_text: str = article_data.get("body", "")
        paragraphs = [p.strip() for p in body_text.split("\n") if p.strip()]

        return template.render(
            country=country_key,
            brand_name=country_cfg.get("name", ""),
            title=article_data.get("title", ""),
            body_paragraphs=paragraphs,
            hashtags=article_data.get("hashtags", []),
            fomus_insert=article_data.get("fomus_insert", ""),
            source_link=article_data.get("source_link", ""),
            source_title=article_data.get("source_title", ""),
            published_at=article_data.get("published_at", ""),
            published_at_display=article_data.get("published_at_display", ""),
            category=article_data.get("category", ""),
        )

    def render_sns(
        self,
        content: dict[str, Any],
        platform: str,
    ) -> str:
        """Render SNS content through a Jinja2 template.

        Args:
            content: Platform-specific content dict from generate_sns_caption.
            platform: One of 'instagram', 'x', 'tiktok'.

        Returns:
            Rendered text string.
        """
        template_name = f"sns_{platform}.txt.j2"
        template = self.jinja_env.get_template(template_name)
        return template.render(**content)

    def optimize_hashtags(
        self,
        topic: str,
        country_key: str,
        platform: str = "instagram",
        language: str = "ja",
    ) -> list[str]:
        """Optimize hashtags using AI for maximum reach.

        Args:
            topic: Content topic for context.
            country_key: Country to pull base hashtags from.
            platform: Target platform.
            language: Target language.

        Returns:
            Optimized list of hashtags.
        """
        country_cfg = self.countries.get(country_key, {})
        base_hashtags = country_cfg.get("hashtags", {}).get(language, [])
        return self.openai.optimize_hashtags(
            topic=topic,
            platform=platform,
            base_hashtags=base_hashtags,
            language=language,
        )

    # ------------------------------------------------------------------
    # Internal: country-level generation
    # ------------------------------------------------------------------

    def _generate_country(
        self,
        country_key: str,
        country_cfg: dict[str, Any],
        articles: list[dict[str, Any]],
        platforms: tuple[str, ...],
        languages: tuple[str, ...] | None,
    ) -> list[dict[str, Any]]:
        """Generate content for all articles of a single country."""
        all_content: list[dict[str, Any]] = []
        for article in articles:
            content_items = self._generate_for_single_article(
                article, country_key, country_cfg, platforms, languages
            )
            all_content.extend(content_items)
        logger.info(
            "%s: generated %d content pieces from %d articles",
            country_key, len(all_content), len(articles),
        )
        return all_content

    def _generate_for_single_article(
        self,
        article: dict[str, Any],
        country_key: str,
        country_cfg: dict[str, Any],
        platforms: tuple[str, ...],
        languages: tuple[str, ...] | None,
    ) -> list[dict[str, Any]]:
        """Generate content for one article across platforms and languages."""
        tone = country_cfg.get("tone", "")
        country_languages = languages or tuple(country_cfg.get("languages", ["ja"]))
        country_hashtags: dict[str, list[str]] = country_cfg.get("hashtags", {})

        # Determine FOMUS insertion for this article
        insert_fomus = self._should_insert_fomus()

        # Build topic string from article data
        topic = self._build_topic_string(article)

        content_items: list[dict[str, Any]] = []

        for lang in country_languages:
            system_prompt = self._build_system_prompt(lang, tone, insert_fomus)
            hashtags = country_hashtags.get(lang, [])

            for platform in platforms:
                logger.debug(
                    "Generating %s/%s content for '%s' [%s]",
                    platform, lang, article.get("title", "")[:40], country_key,
                )
                sns_content = self.openai.generate_sns_caption(
                    topic=topic,
                    platform=platform,
                    tone=tone,
                    language=lang,
                    hashtags=hashtags,
                    system_prompt=system_prompt,
                )
                content_items.append({
                    "country": country_key,
                    "brand_name": country_cfg.get("name", ""),
                    "platform": platform,
                    "language": lang,
                    "tone": tone,
                    "source_article": {
                        "title": article.get("title", ""),
                        "link": article.get("link", ""),
                        "investor_score": article.get("investor_score", {}),
                    },
                    "content": sns_content,
                    "fomus_included": insert_fomus,
                })

        return content_items

    # ------------------------------------------------------------------
    # FOMUS stealth branding
    # ------------------------------------------------------------------

    def _should_insert_fomus(self) -> bool:
        """Decide whether to include FOMUS branding (20% probability)."""
        if not self.fomus_config.get("stealth_mode", False):
            return False
        ratio = self.fomus_config.get("appearance_ratio", 0.2)
        return random.random() < ratio

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(
        self, language: str, tone: str, include_fomus: bool
    ) -> str:
        """Compose the full system prompt based on language, tone, and FOMUS flag."""
        base_prompt = LANGUAGE_PROMPTS.get(language, COPYWRITER_EN_PROMPT)

        tone_instruction = self._get_tone_instruction(tone)
        prompt_parts = [base_prompt, "", tone_instruction]

        if include_fomus:
            prompt_parts.extend(["", "---", "", FOMUS_STEALTH_PROMPT])

        return "\n".join(prompt_parts)

    @staticmethod
    def _get_tone_instruction(tone: str) -> str:
        """Return a tone-specific writing instruction block."""
        instructions: dict[str, str] = {
            "investment-luxury": (
                "## トーン補足: Investment-Luxury\n"
                "ドバイを舞台とした投資・節税・ラグジュアリーライフスタイルの文脈で執筆。\n"
                "不動産ROI、ゴールデンビザ、タックスメリットなど具体的なベネフィットを示唆しつつ、\n"
                "上質なライフスタイルへの憧れを醸成する。"
            ),
            "culture-business": (
                "## トーン補足: Culture-Business\n"
                "サウジアラビアのビジョン2030を軸に、日本文化との融合・メガプロジェクトの可能性を発信。\n"
                "NEOM、紅海プロジェクト、エンタメ産業などの成長セクターに言及し、\n"
                "日本企業・投資家にとっての商機を知的に提示する。"
            ),
            "royal-tradition": (
                "## トーン補足: Royal-Tradition\n"
                "ブルネイ王室の伝統と格式を尊重しつつ、日本の伝統工芸・ハラールビジネスとの\n"
                "接点を探る。「知られざる富裕国」としてのブルネイの魅力を、\n"
                "品格ある語り口で伝える。"
            ),
        }
        return instructions.get(tone, f"## トーン: {tone}\nこのトーンに合わせて執筆してください。")

    @staticmethod
    def _build_topic_string(article: dict[str, Any]) -> str:
        """Extract a concise topic string from an analyzed article dict."""
        title = article.get("title", "")
        summary_data = article.get("summary", {})
        summary_text = (
            summary_data.get("summary", "")
            if isinstance(summary_data, dict)
            else str(summary_data)
        )
        score_data = article.get("investor_score", {})
        angle = score_data.get("angle", "") if isinstance(score_data, dict) else ""

        parts = [f"記事タイトル: {title}"]
        if summary_text:
            parts.append(f"要約: {summary_text}")
        if angle:
            parts.append(f"切り口: {angle}")
        return "\n".join(parts)


# ------------------------------------------------------------------
# CLI entry point for testing
# ------------------------------------------------------------------

def main() -> None:
    """Test run: generate content from sample article data."""
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    # Sample article data (mimics TrendAnalyst output)
    sample_news: dict[str, list[dict[str, Any]]] = {
        "dubai": [
            {
                "country": "dubai",
                "brand_name": "Connect Dubai",
                "title": "Dubai's Golden Visa attracts record Japanese applicants in 2025",
                "link": "https://example.com/news/1",
                "summary": {
                    "summary": "ドバイのゴールデンビザ申請で日本人が過去最多を記録",
                    "key_topics": ["ゴールデンビザ", "日本人投資家"],
                    "relevance": "日本の富裕層のドバイ移住トレンドを示す重要指標",
                },
                "investor_score": {
                    "score": 92,
                    "reason": "日本人投資家の関心が直接的に高いテーマ",
                    "angle": "節税と生活の質の両立を実現するドバイ移住の最新動向",
                    "content_type": "investment",
                },
            },
        ],
    }

    writer = Copywriter()
    results = writer.generate_all(sample_news, platforms=("instagram", "x"))

    for country_key, items in results.items():
        print(f"\n{'='*60}")
        print(f"  {country_key.upper()} - {len(items)} content pieces")
        print(f"{'='*60}")
        for item in items:
            print(f"\n  [{item['platform'].upper()}] ({item['language']})")
            print(f"  FOMUS: {'Yes' if item['fomus_included'] else 'No'}")
            import json
            print(f"  Content: {json.dumps(item['content'], ensure_ascii=False, indent=4)}")


if __name__ == "__main__":
    main()
