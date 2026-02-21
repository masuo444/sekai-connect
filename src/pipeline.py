"""Main pipeline for Connect-Sekai: orchestrates all agents."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from src.agents.trend_analyst import TrendAnalyst
from src.database.models import Database

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "countries.yaml"


class Pipeline:
    """Orchestrates the full Connect-Sekai content pipeline."""

    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        with open(config_path, "r", encoding="utf-8") as f:
            self.config: dict[str, Any] = yaml.safe_load(f)
        self.countries: dict[str, dict[str, Any]] = self.config.get("countries", {})
        self.fomus: dict[str, Any] = self.config.get("fomus", {})
        self.db = Database()
        self.db.init_db()

    # ------------------------------------------------------------------
    # Step 1 : Collect news
    # ------------------------------------------------------------------

    def step_collect(self) -> dict[str, list[dict[str, Any]]]:
        """Collect news for all countries and persist to DB."""
        logger.info("=== Step 1: News Collection ===")
        analyst = TrendAnalyst()
        all_results = analyst.collect_all()

        saved_count = 0
        for country_key, articles in all_results.items():
            for article in articles:
                summary_text = ""
                if isinstance(article.get("summary"), dict):
                    summary_text = article["summary"].get("summary", "")
                elif isinstance(article.get("summary"), str):
                    summary_text = article["summary"]

                score = 0.0
                if isinstance(article.get("investor_score"), dict):
                    score = float(article["investor_score"].get("score", 0))

                self.db.insert_news_item(
                    country=country_key,
                    title=article.get("title", ""),
                    url=article.get("link", ""),
                    source=article.get("source_feed", ""),
                    summary=summary_text,
                    relevance_score=score,
                )
                saved_count += 1

        logger.info("Collected and saved %d news items to DB.", saved_count)
        return all_results

    # ------------------------------------------------------------------
    # Step 2 : Generate articles
    # ------------------------------------------------------------------

    def step_generate_articles(self) -> list[dict[str, Any]]:
        """Generate articles from unprocessed news items."""
        logger.info("=== Step 2: Article Generation ===")
        news_items = self.db.get_news_items(status="new")
        if not news_items:
            logger.info("No new news items to process.")
            return []

        generated: list[dict[str, Any]] = []

        try:
            from src.agents.copywriter import Copywriter
            writer = Copywriter()
        except ImportError:
            logger.warning(
                "Copywriter agent not available yet. "
                "Generating placeholder articles."
            )
            writer = None

        for item in news_items:
            country_key = item["country"]
            country_cfg = self.countries.get(country_key, {})
            languages = country_cfg.get("languages", ["ja"])
            platforms = ["instagram", "web"]

            for lang in languages:
                for platform in platforms:
                    if writer is not None:
                        result = writer.generate(
                            news_item=item,
                            country_config=country_cfg,
                            language=lang,
                            platform=platform,
                            fomus_config=self.fomus,
                        )
                        article_id = self.db.insert_article(
                            news_item_id=item["id"],
                            country=country_key,
                            language=lang,
                            platform=platform,
                            title=result.get("title", item["title"]),
                            body=result.get("body", ""),
                            caption=result.get("caption", ""),
                            hashtags=result.get("hashtags", ""),
                            has_fomus_mention=result.get("has_fomus_mention", False),
                        )
                    else:
                        article_id = self.db.insert_article(
                            news_item_id=item["id"],
                            country=country_key,
                            language=lang,
                            platform=platform,
                            title=item["title"],
                            body=f"[Placeholder] {item.get('summary', '')}",
                            caption="",
                            hashtags="",
                        )

                    generated.append({"article_id": article_id, "news_id": item["id"]})

            self.db.update_news_status(item["id"], "processed")

        logger.info("Generated %d articles from %d news items.", len(generated), len(news_items))
        return generated

    # ------------------------------------------------------------------
    # Step 3 : Generate visuals
    # ------------------------------------------------------------------

    def step_generate_visuals(self) -> list[dict[str, Any]]:
        """Generate visual assets for draft articles."""
        logger.info("=== Step 3: Visual Generation ===")
        articles = self.db.get_articles(status="draft")
        if not articles:
            logger.info("No draft articles to create visuals for.")
            return []

        created: list[dict[str, Any]] = []

        try:
            from src.agents.creative_dir import CreativeDirector
            director = CreativeDirector()
        except ImportError:
            logger.warning(
                "CreativeDirector agent not available yet. "
                "Skipping visual generation."
            )
            director = None

        for article in articles:
            if director is not None:
                result = director.generate(
                    article=article,
                    country_config=self.countries.get(article["country"], {}),
                )
                asset_id = self.db.insert_visual_asset(
                    article_id=article["id"],
                    image_path=result.get("image_path", ""),
                    prompt_used=result.get("prompt_used", ""),
                    aspect_ratio=result.get("aspect_ratio", "1:1"),
                )
            else:
                asset_id = self.db.insert_visual_asset(
                    article_id=article["id"],
                    image_path="[placeholder]",
                    prompt_used="",
                    aspect_ratio="1:1",
                )

            created.append({"asset_id": asset_id, "article_id": article["id"]})
            self.db.update_article_status(article["id"], "approved")

        logger.info("Created %d visual assets.", len(created))
        return created

    # ------------------------------------------------------------------
    # Step 4 : Schedule distribution
    # ------------------------------------------------------------------

    def step_schedule(self) -> list[dict[str, Any]]:
        """Create distribution queue entries for approved articles."""
        logger.info("=== Step 4: Distribution Scheduling ===")
        articles = self.db.get_articles(status="approved")
        if not articles:
            logger.info("No approved articles to schedule.")
            return []

        scheduled: list[dict[str, Any]] = []

        for article in articles:
            assets = self.db.get_visual_assets(article_id=article["id"])
            if not assets:
                logger.warning("Article %d has no visual asset, skipping.", article["id"])
                continue

            country_cfg = self.countries.get(article["country"], {})
            tz_name = country_cfg.get("timezone", "UTC")
            utc_offset = country_cfg.get("utc_offset", 0)
            prime_times = country_cfg.get("prime_times", ["12:00"])

            # Pick the next prime-time slot from now
            base_time = datetime.now(timezone.utc) + timedelta(hours=1)
            scheduled_time = self._next_prime_time(base_time, utc_offset, prime_times)

            dist_id = self.db.insert_distribution(
                article_id=article["id"],
                visual_asset_id=assets[0]["id"],
                platform=article["platform"],
                scheduled_time=scheduled_time.isoformat(),
                tz=tz_name,
            )
            self.db.update_article_status(article["id"], "scheduled")
            scheduled.append({"dist_id": dist_id, "article_id": article["id"]})

        logger.info("Scheduled %d items for distribution.", len(scheduled))
        return scheduled

    # ------------------------------------------------------------------
    # Step 5 : Publish to SNS
    # ------------------------------------------------------------------

    def step_publish(self) -> list[dict[str, Any]]:
        """Publish pending items in the distribution queue to each SNS."""
        logger.info("=== Step 5: SNS Publishing ===")
        queue = self.db.get_distribution_queue(status="pending")
        if not queue:
            logger.info("No pending items in distribution queue.")
            return []

        from src.sns.instagram import InstagramClient
        from src.sns.tiktok import TikTokClient
        from src.sns.twitter import TwitterClient

        ig = InstagramClient()
        tt = TikTokClient()
        tw = TwitterClient()

        results: list[dict[str, Any]] = []

        for item in queue:
            dist_id = item["id"]
            platform = item["platform"]
            article = self.db.get_article(item["article_id"])
            asset = self.db.get_visual_asset(item["visual_asset_id"])

            if not article or not asset:
                logger.warning(
                    "Distribution %d: article or asset missing, marking failed.",
                    dist_id,
                )
                self.db.update_distribution_status(dist_id, "failed")
                continue

            caption = article.get("caption", "") or article.get("title", "")
            hashtags = article.get("hashtags", "")
            if hashtags:
                caption = f"{caption}\n\n{hashtags}"
            image_path = asset.get("image_path", "")

            try:
                if platform == "instagram" and ig.enabled:
                    ig.publish_image_post(image_url=image_path, caption=caption)
                    logger.info("Published dist %d to Instagram.", dist_id)

                elif platform == "tiktok" and tt.enabled:
                    tt.publish_photo_post(image_urls=[image_path], caption=caption)
                    logger.info("Published dist %d to TikTok.", dist_id)

                elif platform == "twitter" and tw.enabled:
                    text = article.get("caption", "") or article.get("title", "")
                    if hashtags:
                        text = f"{text}\n{hashtags}"
                    # 280文字制限
                    if len(text) > 280:
                        text = text[:277] + "..."
                    if image_path and image_path != "[placeholder]":
                        tw.publish_image_post(text=text, image_path=image_path)
                    else:
                        tw.publish_text_post(text=text)
                    logger.info("Published dist %d to X (Twitter).", dist_id)

                else:
                    logger.info(
                        "Skipping dist %d: platform=%s client not enabled.",
                        dist_id,
                        platform,
                    )
                    continue

                self.db.update_distribution_status(
                    dist_id,
                    "published",
                    published_at=datetime.now(timezone.utc).isoformat(),
                )
                self.db.update_article_status(article["id"], "published")
                results.append({"dist_id": dist_id, "status": "published"})

            except Exception:
                logger.exception("Failed to publish dist %d to %s.", dist_id, platform)
                self.db.update_distribution_status(dist_id, "failed")
                results.append({"dist_id": dist_id, "status": "failed"})

        published = sum(1 for r in results if r["status"] == "published")
        failed = sum(1 for r in results if r["status"] == "failed")
        logger.info(
            "Publishing complete: %d published, %d failed.", published, failed,
        )
        return results

    # ------------------------------------------------------------------
    # Step 6 : Static Site Generation
    # ------------------------------------------------------------------

    def step_export_site(self) -> None:
        """Generate static HTML site from published articles."""
        logger.info("=== Step 6: Static Site Generation ===")
        from src.site_generator import SiteGenerator
        generator = SiteGenerator()
        generator.generate_all()

    # ------------------------------------------------------------------
    # Full run
    # ------------------------------------------------------------------

    def run_all(self) -> None:
        """Execute the full pipeline: collect -> generate -> visuals -> schedule -> publish -> export site."""
        logger.info("======== Connect-Sekai Pipeline START ========")
        self.step_collect()
        self.step_generate_articles()
        self.step_generate_visuals()
        self.step_schedule()
        self.step_publish()
        self.step_export_site()
        logger.info("======== Connect-Sekai Pipeline COMPLETE ========")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _next_prime_time(
        base_utc: datetime,
        utc_offset: int,
        prime_times: list[str],
    ) -> datetime:
        """Return the next prime-time slot (UTC) that is after *base_utc*."""
        local_now = base_utc + timedelta(hours=utc_offset)
        today = local_now.date()

        for pt_str in prime_times:
            h, m = map(int, pt_str.split(":"))
            candidate_local = datetime(
                today.year, today.month, today.day, h, m,
                tzinfo=timezone(timedelta(hours=utc_offset)),
            )
            if candidate_local > local_now.replace(
                tzinfo=timezone(timedelta(hours=utc_offset))
            ):
                return candidate_local.astimezone(timezone.utc)

        # All prime times have passed today; use first slot tomorrow
        tomorrow = today + timedelta(days=1)
        h, m = map(int, prime_times[0].split(":"))
        candidate_local = datetime(
            tomorrow.year, tomorrow.month, tomorrow.day, h, m,
            tzinfo=timezone(timedelta(hours=utc_offset)),
        )
        return candidate_local.astimezone(timezone.utc)
