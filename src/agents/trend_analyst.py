"""News collection and trend analysis agent for Connect-Sekai."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ssl
import urllib.request

import certifi
import feedparser
import yaml

from src.api.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "countries.yaml"
DATA_NEWS_DIR = PROJECT_ROOT / "data" / "news"
MAX_ARTICLES_PER_FEED = 10


class TrendAnalyst:
    """Collects and analyzes news for each configured country."""

    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.countries: dict[str, dict] = self.config.get("countries", {})
        self.gemini = GeminiClient()

    def collect_all(self) -> dict[str, list[dict[str, Any]]]:
        """Collect and analyze news for all countries. Returns {country_key: [articles]}."""
        results: dict[str, list[dict[str, Any]]] = {}
        for country_key, country_cfg in self.countries.items():
            logger.info("Collecting news for %s ...", country_key)
            results[country_key] = self._collect_country(country_key, country_cfg)
        return results

    def collect_country(self, country_key: str) -> list[dict[str, Any]]:
        """Collect and analyze news for a single country."""
        country_cfg = self.countries.get(country_key)
        if not country_cfg:
            raise ValueError(f"Unknown country: {country_key}")
        return self._collect_country(country_key, country_cfg)

    def _collect_country(
        self, country_key: str, country_cfg: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Fetch RSS feeds, summarize, and score articles for one country."""
        raw_articles = self._fetch_feeds(country_cfg.get("news_sources", []))
        tone = country_cfg.get("tone", "")
        topics = country_cfg.get("topics", [])
        analyzed: list[dict[str, Any]] = []

        for article in raw_articles:
            title = article.get("title", "")
            description = article.get("description", "")

            summary_data = self.gemini.summarize_article(title, description, country_key)
            score_data = self.gemini.score_for_investors(
                title,
                summary_data.get("summary", ""),
                country_key,
                tone,
                topics,
            )

            analyzed.append({
                "country": country_key,
                "brand_name": country_cfg.get("name", ""),
                "title": title,
                "link": article.get("link", ""),
                "published": article.get("published", ""),
                "source_feed": article.get("source_feed", ""),
                "summary": summary_data,
                "investor_score": score_data,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            })

        # Sort by investor score descending
        analyzed.sort(key=lambda a: a["investor_score"].get("score", 0), reverse=True)
        logger.info(
            "%s: %d articles collected and scored", country_key, len(analyzed)
        )
        return analyzed

    def _fetch_feeds(self, feed_urls: list[str]) -> list[dict[str, str]]:
        """Parse RSS feeds and return flat list of article dicts."""
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        handler = urllib.request.HTTPSHandler(context=ssl_ctx)
        articles: list[dict[str, str]] = []
        for url in feed_urls:
            try:
                feed = feedparser.parse(url, handlers=[handler])
                for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
                    articles.append({
                        "title": entry.get("title", ""),
                        "description": entry.get("summary", entry.get("description", "")),
                        "link": entry.get("link", ""),
                        "published": entry.get("published", ""),
                        "source_feed": url,
                    })
                logger.info("Fetched %d entries from %s", len(feed.entries), url)
            except Exception as e:
                logger.warning("Failed to fetch feed %s: %s", url, e)
        return articles

    @staticmethod
    def save_results(
        results: dict[str, list[dict[str, Any]]],
        output_dir: Path = DATA_NEWS_DIR,
    ) -> dict[str, Path]:
        """Save results to data/news/ as JSON files. Returns {country_key: file_path}."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        output_dir.mkdir(parents=True, exist_ok=True)
        saved: dict[str, Path] = {}
        for country_key, articles in results.items():
            file_path = output_dir / f"{country_key}_{date_str}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"country": country_key, "date": date_str, "articles": articles},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            saved[country_key] = file_path
            logger.info("Saved %d articles to %s", len(articles), file_path)
        return saved


def main() -> None:
    """Test run: collect news for all countries, save to JSON, and print top results."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    analyst = TrendAnalyst()
    results = analyst.collect_all()

    # Save to data/news/
    saved_files = analyst.save_results(results)
    for country_key, path in saved_files.items():
        print(f"Saved: {path}")

    # Print summary
    for country_key, articles in results.items():
        print(f"\n{'='*60}")
        print(f"  {country_key.upper()} - Top articles ({len(articles)} total)")
        print(f"{'='*60}")
        for article in articles[:3]:
            score = article["investor_score"]
            print(f"\n  [{score.get('score', '?')}/100] {article['title']}")
            print(f"  Summary: {article['summary'].get('summary', 'N/A')}")
            print(f"  Angle:   {score.get('angle', 'N/A')}")
            print(f"  Type:    {score.get('content_type', 'N/A')}")
            print(f"  Link:    {article['link']}")


if __name__ == "__main__":
    main()
