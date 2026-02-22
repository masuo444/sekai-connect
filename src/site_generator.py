"""Connect-Sekai 静的サイト生成スクリプト。

SQLite の記事データから HTML を自動生成する。
パイプライン実行後に呼び出され、site/ ディレクトリに
静的 HTML ファイルを出力する。

リージョン（地域）とジャンル（カテゴリ）の両方でフィルタリング
された一覧ページを全 3 カ国に対して生成する。
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape as xml_escape

import yaml
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
SITE_DIR = BASE_DIR / "site"
TEMPLATE_DIR = SITE_DIR / "templates"
DB_PATH = BASE_DIR / "data" / "connect_nexus.db"
CONFIG_PATH = BASE_DIR / "config" / "countries.yaml"

# ---------------------------------------------------------------------------
# Site URL (change after domain acquisition)
# ---------------------------------------------------------------------------

SITE_URL = "https://connect-sekai.com"

# ---------------------------------------------------------------------------
# Country configuration
# ---------------------------------------------------------------------------

COUNTRIES: dict[str, dict[str, str]] = {
    "uae": {
        "name": "Connect UAE",
        "name_ja": "コネクトUAE",
        "description": "投資・不動産・ラグジュアリー",
        "description_en": "Investment, Real Estate & Luxury",
    },
    "saudi": {
        "name": "Connect Saudi",
        "name_ja": "コネクトサウジ",
        "description": "ビジョン2030・日本文化・メガプロジェクト",
        "description_en": "Vision 2030, Japanese Culture & Mega Projects",
    },
    "brunei": {
        "name": "Connect Brunei",
        "name_ja": "コネクトブルネイ",
        "description": "王室・ハラール×日本・工芸",
        "description_en": "Royal Heritage, Halal × Japan & Craftsmanship",
    },
    "japan": {
        "name": "Connect Japan",
        "name_ja": "コネクトジャパン",
        "description": "ビジネス・テクノロジー・アニメ・漫画",
        "description_en": "Business, Technology, Anime & Manga",
    },
}

# ---------------------------------------------------------------------------
# Region keyword mapping (used for classification)
# Each country maps region keys to a list of match keywords.
# ---------------------------------------------------------------------------

REGION_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "uae": {
        "dubai": ["Dubai", "ドバイ"],
        "abu_dhabi": ["Abu Dhabi", "アブダビ"],
    },
    "saudi": {
        "riyadh": ["Riyadh", "リヤド"],
        "jeddah": ["Jeddah", "ジェッダ"],
        "neom": ["NEOM"],
    },
    "brunei": {
        "bandar": ["Bandar", "バンダル"],
    },
    "japan": {
        "tokyo": ["Tokyo", "東京", "渋谷", "新宿", "秋葉原", "Akihabara", "Shibuya", "Shinjuku"],
        "osaka": ["Osaka", "大阪", "関西", "Kansai"],
    },
}

# Region slug mapping (region_key -> URL slug)
REGION_SLUGS: dict[str, dict[str, str]] = {
    "uae": {
        "dubai": "dubai",
        "abu_dhabi": "abu-dhabi",
        "others": "others",
    },
    "saudi": {
        "riyadh": "riyadh",
        "jeddah": "jeddah",
        "neom": "neom",
    },
    "japan": {
        "tokyo": "tokyo",
        "osaka": "osaka",
        "others": "others",
        "others": "others",
    },
    "brunei": {
        "bandar": "bandar",
        "others": "others",
    },
}


def _body_to_html(text: str) -> str:
    """Convert plain-text body to simple HTML paragraphs."""
    if not text:
        return ""
    # Split on double newlines into paragraphs
    paragraphs = text.split("\n\n")
    parts: list[str] = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        # Replace single newlines within a paragraph with <br>
        p = p.replace("\n", "<br>")
        parts.append(f"<p>{p}</p>")
    return "\n".join(parts)


def _excerpt(text: str, max_len: int = 120) -> str:
    """Return a plain-text excerpt from article body."""
    if not text:
        return ""
    clean = text.replace("\n", " ").strip()
    if len(clean) <= max_len:
        return clean
    return clean[:max_len] + "..."


def _load_config() -> dict[str, Any]:
    """Load and return the countries.yaml configuration."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class SiteGenerator:
    """Generates the Connect-Sekai static HTML site from the SQLite database."""

    def __init__(self) -> None:
        self.db_path = DB_PATH
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=True,
        )
        # Load configuration from YAML
        config = _load_config()
        self.genres_config: dict[str, Any] = config.get("genres", {})
        self.countries_config: dict[str, Any] = config.get("countries", {})

        # Track generated pages for sitemap generation.
        # Each entry: {"rel_path": str, "priority": str, "changefreq": str}
        self._generated_pages: list[dict[str, str]] = []

        # Build regions config per country from YAML
        # Each region gets: name_ja, name_en, slug, keywords
        self.regions_config: dict[str, dict[str, dict[str, Any]]] = {}
        for country_key in COUNTRIES:
            country_cfg = self.countries_config.get(country_key, {})
            yaml_regions = country_cfg.get("regions", {})
            regions: dict[str, dict[str, Any]] = {}
            for region_key, region_info in yaml_regions.items():
                slug = REGION_SLUGS.get(country_key, {}).get(region_key, region_key)
                keywords = REGION_KEYWORDS.get(country_key, {}).get(region_key, [])
                regions[region_key] = {
                    "name_ja": region_info.get("name_ja", ""),
                    "name_en": region_info.get("name_en", ""),
                    "slug": slug,
                    "keywords": keywords,
                }
            self.regions_config[country_key] = regions

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _get_articles(
        self,
        country: Optional[str] = None,
        language: str = "ja",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query articles with joined image and source data.

        Each article dict is augmented with computed ``genre`` and
        ``region`` fields based on keyword classification.
        """
        conn = self._get_conn()
        try:
            clauses = [
                "a.status IN ('approved', 'scheduled', 'published')",
                "a.language = ?",
            ]
            params: list[Any] = [language]

            if country:
                clauses.append("a.country = ?")
                params.append(country)

            where = " AND ".join(clauses)
            params.append(limit)

            query = f"""
                SELECT
                    a.*,
                    va.image_path,
                    ni.url AS source_url
                FROM articles a
                LEFT JOIN visual_assets va ON va.article_id = a.id
                LEFT JOIN news_items ni ON ni.id = a.news_item_id
                WHERE {where}
                ORDER BY a.created_at DESC
                LIMIT ?
            """
            rows = conn.execute(query, params).fetchall()

            articles: list[dict[str, Any]] = []
            for row in rows:
                d = dict(row)
                d["body_html"] = _body_to_html(d.get("body", ""))
                d["excerpt"] = _excerpt(d.get("body", ""))

                # Determine image file extension from stored path
                img_path = d.get("image_path") or ""
                if img_path and img_path != "[placeholder]":
                    d["image_ext"] = Path(img_path).suffix or ".jpg"
                else:
                    d["image_ext"] = ".jpg"

                # Classify genre and region
                title = d.get("title", "") or ""
                body = d.get("body", "") or ""
                article_country = d.get("country", "")

                d["genre"] = self._classify_genre(title, body, self.genres_config)
                d["region"] = self._classify_region(
                    title, body, article_country, self.regions_config.get(article_country, {}),
                )

                articles.append(d)
            return articles
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Classification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_genre(
        title: str,
        body: str,
        genres_config: dict[str, Any],
    ) -> str:
        """Classify an article into a genre based on keyword matching.

        Checks title+body against each genre's keywords and returns the
        genre key with the most keyword matches. Defaults to "business"
        if no keywords match.
        """
        text = (title + " " + body).lower()
        best_genre = "business"
        best_count = 0

        for genre_key, genre_info in genres_config.items():
            keywords = genre_info.get("keywords", [])
            count = sum(1 for kw in keywords if kw.lower() in text)
            if count > best_count:
                best_count = count
                best_genre = genre_key

        return best_genre

    @staticmethod
    def _classify_region(
        title: str,
        body: str,
        country_key: str,
        regions_config: dict[str, dict[str, Any]],
    ) -> str:
        """Classify an article into a region based on keyword matching.

        Checks title+body against each region's keywords for the given
        country. Returns the region key of the first match, or "others"
        if no keywords match.
        """
        text = (title + " " + body).lower()

        for region_key, region_info in regions_config.items():
            if region_key == "others":
                continue
            keywords = region_info.get("keywords", [])
            if any(kw.lower() in text for kw in keywords):
                return region_key

        return "others"

    # ------------------------------------------------------------------
    # SEO / AIO helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _lang_path(rel_path: str, lang: str) -> str:
        """Compute the language-independent page path for language switching.

        Japanese pages live at root (no prefix), English under ``en/``,
        Arabic under ``ar/``.  This strips the lang prefix so the header
        template can build correct cross-language links.
        """
        if lang == "ja":
            return rel_path
        return rel_path[len(lang) + 1:]

    @staticmethod
    def _make_breadcrumbs(items: list[tuple[str, str]]) -> list[dict]:
        """Generate breadcrumb list from (name, relative_url) tuples."""
        return [{"name": name, "url": f"{SITE_URL}/{url}"} for name, url in items]

    @staticmethod
    def _get_related_articles(
        article: dict,
        all_articles: list[dict],
        max_count: int = 3,
    ) -> list[dict]:
        """Get related articles in the same genre, excluding self."""
        return [
            a
            for a in all_articles
            if a["id"] != article["id"] and a.get("genre") == article.get("genre")
        ][:max_count]

    @staticmethod
    def _iso_date(value: Any) -> str:
        """Convert a date value to ISO 8601 format string.

        Accepts datetime objects, ISO-like strings, or falls back to the
        current UTC time.
        """
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        if isinstance(value, str) and value:
            # Already looks like an ISO date – normalise quickly
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except ValueError:
                pass
        return datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).isoformat()

    # ------------------------------------------------------------------
    # Generators
    # ------------------------------------------------------------------

    def _write_html(self, rel_path: str, html: str) -> None:
        """Write rendered HTML to the site output directory."""
        out_path = SITE_DIR / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
        logger.debug("Wrote %s", out_path)

    def _generate_index(self, lang: str = "ja") -> None:
        """Generate the top-level index page for the given language."""
        articles = self._get_articles(language=lang, limit=50)
        template = self.env.get_template("index.html")

        if lang == "ja":
            base_path = ""
            rel_path = "index.html"
        else:
            base_path = "../"
            rel_path = f"{lang}/index.html"

        now_iso = self._iso_date(None)
        breadcrumbs = self._make_breadcrumbs([("ホーム", rel_path.replace("index.html", "").rstrip("/") or "")])

        html = template.render(
            title="Connect-Sekai",
            description="Business Media Bridging Japan with UAE, Saudi Arabia & Brunei",
            lang=lang,
            base_path=base_path,
            lang_path=self._lang_path(rel_path, lang),
            countries=COUNTRIES,
            articles=articles,
            current_country=None,
            genres=self.genres_config,
            regions=None,
            current_region=None,
            current_genre=None,
            # SEO / AIO variables
            site_url=SITE_URL,
            canonical_url=f"{SITE_URL}/{rel_path}",
            page_type="website",
            breadcrumbs=breadcrumbs,
            published_date_iso=now_iso,
            modified_date_iso=now_iso,
            faq_items=[],
            current_year=self._current_year(),
        )
        self._write_html(rel_path, html)
        self._generated_pages.append(
            {"rel_path": rel_path, "priority": "1.0", "changefreq": "daily"},
        )
        logger.info("Generated index page: %s (%d articles)", rel_path, len(articles))

    def _generate_country_pages(self, lang: str = "ja") -> None:
        """Generate country listing, region, and genre pages for each country."""
        template = self.env.get_template("country.html")

        for country_key, country_info in COUNTRIES.items():
            articles = self._get_articles(country=country_key, language=lang, limit=50)
            regions = self.regions_config.get(country_key, {})

            if lang == "ja":
                base_path = "../"
                rel_path = f"{country_key}/index.html"
            else:
                base_path = "../../"
                rel_path = f"{lang}/{country_key}/index.html"

            country_name = country_info.get("name_ja", country_info["name"])
            now_iso = self._iso_date(None)
            breadcrumbs = self._make_breadcrumbs([
                ("ホーム", "" if lang == "ja" else f"{lang}/"),
                (country_name, f"{country_key}/" if lang == "ja" else f"{lang}/{country_key}/"),
            ])

            # --- Main country page (all articles) ---
            html = template.render(
                title=country_info["name"],
                description=country_info["description_en"],
                lang=lang,
                base_path=base_path,
                lang_path=self._lang_path(rel_path, lang),
                countries=COUNTRIES,
                country_key=country_key,
                country_info=country_info,
                articles=articles,
                current_country=country_key,
                regions=regions,
                genres=self.genres_config,
                current_region=None,
                current_genre=None,
                current_region_slug=None,
                # SEO / AIO variables
                site_url=SITE_URL,
                canonical_url=f"{SITE_URL}/{rel_path}",
                page_type="collection",
                breadcrumbs=breadcrumbs,
                published_date_iso=now_iso,
                modified_date_iso=now_iso,
                faq_items=[],
                current_year=self._current_year(),
            )
            self._write_html(rel_path, html)
            self._generated_pages.append(
                {"rel_path": rel_path, "priority": "0.9", "changefreq": "daily"},
            )
            logger.info(
                "Generated country page: %s (%d articles)",
                rel_path,
                len(articles),
            )

            # --- Region pages ---
            self._generate_region_pages(
                lang, template, country_key, country_info, regions, articles,
            )

            # --- Genre pages ---
            self._generate_genre_pages(
                lang, template, country_key, country_info, regions, articles,
            )

    def _generate_region_pages(
        self,
        lang: str,
        template: Any,
        country_key: str,
        country_info: dict[str, str],
        regions: dict[str, dict[str, Any]],
        all_articles: list[dict[str, Any]],
    ) -> None:
        """Generate sub-region pages for a country."""
        for region_key, region_info in regions.items():
            slug = region_info.get("slug", region_key)

            # Filter articles by classified region
            region_articles = [
                a for a in all_articles if a.get("region") == region_key
            ]

            if lang == "ja":
                base_path = "../../"
                rel_path = f"{country_key}/{slug}/index.html"
            else:
                base_path = "../../../"
                rel_path = f"{lang}/{country_key}/{slug}/index.html"

            country_name = country_info.get("name_ja", country_info["name"])
            region_name = region_info.get("name_ja", region_info.get("name_en", slug))
            now_iso = self._iso_date(None)
            breadcrumbs = self._make_breadcrumbs([
                ("ホーム", "" if lang == "ja" else f"{lang}/"),
                (country_name, f"{country_key}/" if lang == "ja" else f"{lang}/{country_key}/"),
                (region_name, f"{country_key}/{slug}/" if lang == "ja" else f"{lang}/{country_key}/{slug}/"),
            ])

            html = template.render(
                title=f"{country_info['name']} - {region_info['name_en']}",
                description=country_info["description_en"],
                lang=lang,
                base_path=base_path,
                lang_path=self._lang_path(rel_path, lang),
                countries=COUNTRIES,
                country_key=country_key,
                country_info=country_info,
                articles=region_articles,
                current_country=country_key,
                regions=regions,
                genres=self.genres_config,
                current_region=region_key,
                current_genre=None,
                current_region_slug=slug,
                # SEO / AIO variables
                site_url=SITE_URL,
                canonical_url=f"{SITE_URL}/{rel_path}",
                page_type="collection",
                breadcrumbs=breadcrumbs,
                published_date_iso=now_iso,
                modified_date_iso=now_iso,
                faq_items=[],
                current_year=self._current_year(),
            )
            self._write_html(rel_path, html)
            self._generated_pages.append(
                {"rel_path": rel_path, "priority": "0.7", "changefreq": "daily"},
            )
            logger.info(
                "Generated region page: %s/%s (%d articles)",
                country_key,
                slug,
                len(region_articles),
            )

    def _generate_genre_pages(
        self,
        lang: str,
        template: Any,
        country_key: str,
        country_info: dict[str, str],
        regions: dict[str, dict[str, Any]],
        all_articles: list[dict[str, Any]],
    ) -> None:
        """Generate genre pages for a country.

        An article can appear on multiple genre pages if its content
        matches multiple genre keywords, so we re-check against all
        keywords rather than relying solely on the primary genre field.
        """
        for genre_key, genre_info in self.genres_config.items():
            slug = genre_info.get("slug", genre_key)
            genre_keywords = [kw.lower() for kw in genre_info.get("keywords", [])]

            # Include articles whose primary genre matches OR whose
            # content matches any keyword of this genre.
            genre_articles: list[dict[str, Any]] = []
            for a in all_articles:
                if a.get("genre") == genre_key:
                    genre_articles.append(a)
                else:
                    text = (
                        (a.get("title", "") or "") + " " + (a.get("body", "") or "")
                    ).lower()
                    if any(kw in text for kw in genre_keywords):
                        genre_articles.append(a)

            if lang == "ja":
                base_path = "../../"
                rel_path = f"{country_key}/{slug}/index.html"
            else:
                base_path = "../../../"
                rel_path = f"{lang}/{country_key}/{slug}/index.html"

            country_name = country_info.get("name_ja", country_info["name"])
            genre_name = genre_info.get("name_ja", genre_info.get("name_en", slug))
            now_iso = self._iso_date(None)
            breadcrumbs = self._make_breadcrumbs([
                ("ホーム", "" if lang == "ja" else f"{lang}/"),
                (country_name, f"{country_key}/" if lang == "ja" else f"{lang}/{country_key}/"),
                (genre_name, f"{country_key}/{slug}/" if lang == "ja" else f"{lang}/{country_key}/{slug}/"),
            ])

            html = template.render(
                title=f"{country_info['name']} - {genre_info['name_en']}",
                description=country_info["description_en"],
                lang=lang,
                base_path=base_path,
                lang_path=self._lang_path(rel_path, lang),
                countries=COUNTRIES,
                country_key=country_key,
                country_info=country_info,
                articles=genre_articles,
                current_country=country_key,
                regions=regions,
                genres=self.genres_config,
                current_region=None,
                current_genre=genre_key,
                current_region_slug=None,
                # SEO / AIO variables
                site_url=SITE_URL,
                canonical_url=f"{SITE_URL}/{rel_path}",
                page_type="collection",
                breadcrumbs=breadcrumbs,
                published_date_iso=now_iso,
                modified_date_iso=now_iso,
                faq_items=[],
                current_year=self._current_year(),
            )
            self._write_html(rel_path, html)
            self._generated_pages.append(
                {"rel_path": rel_path, "priority": "0.7", "changefreq": "daily"},
            )
            logger.info(
                "Generated genre page: %s/%s (%d articles)",
                country_key,
                slug,
                len(genre_articles),
            )

    def _generate_article_pages(self, lang: str = "ja") -> None:
        """Generate individual article pages."""
        template = self.env.get_template("article.html")
        articles = self._get_articles(language=lang, limit=500)

        for article in articles:
            country_key = article["country"]
            country_info = COUNTRIES.get(country_key, {})
            slug = f"article-{article['id']}"

            # Determine genre display name
            genre_key = article.get("genre", "business")
            genre_cfg = self.genres_config.get(genre_key, {})
            genre_name_ja = genre_cfg.get("name_ja", "ビジネス")
            genre_slug = genre_cfg.get("slug", genre_key)

            if lang == "ja":
                base_path = "../"
                rel_path = f"{country_key}/{slug}.html"
            else:
                base_path = "../../"
                rel_path = f"{lang}/{country_key}/{slug}.html"

            # SEO variables
            country_name = country_info.get("name_ja", country_info.get("name", country_key))
            body_text = article.get("body", "") or ""
            reading_time = len(body_text) // 500 + 1
            related_articles = self._get_related_articles(article, articles)
            published_date_iso = self._iso_date(article.get("created_at"))
            modified_date_iso = self._iso_date(article.get("updated_at") or article.get("created_at"))

            article_title = article.get("title", "")
            breadcrumbs = self._make_breadcrumbs([
                ("ホーム", "" if lang == "ja" else f"{lang}/"),
                (country_name, f"{country_key}/" if lang == "ja" else f"{lang}/{country_key}/"),
                (genre_name_ja, f"{country_key}/{genre_slug}/" if lang == "ja" else f"{lang}/{country_key}/{genre_slug}/"),
                (article_title, rel_path),
            ])

            html = template.render(
                title=article["title"],
                description=_excerpt(article.get("body", ""), 160),
                og_image=f"{SITE_URL}/images/{country_key}-{article['id']}{article.get('image_ext', '.jpg')}",
                lang=lang,
                base_path=base_path,
                lang_path=self._lang_path(rel_path, lang),
                countries=COUNTRIES,
                country_key=country_key,
                country_info=country_info,
                article=article,
                current_country=country_key,
                genres=self.genres_config,
                regions=self.regions_config.get(country_key, {}),
                current_region=None,
                current_genre=genre_key,
                genre_name_ja=genre_name_ja,
                current_region_slug=None,
                # SEO / AIO variables
                site_url=SITE_URL,
                canonical_url=f"{SITE_URL}/{rel_path}",
                page_type="article",
                breadcrumbs=breadcrumbs,
                published_date_iso=published_date_iso,
                modified_date_iso=modified_date_iso,
                reading_time=reading_time,
                related_articles=related_articles,
                faq_items=[],
                current_year=self._current_year(),
            )
            self._write_html(rel_path, html)
            self._generated_pages.append(
                {"rel_path": rel_path, "priority": "0.8", "changefreq": "weekly"},
            )

        logger.info(
            "Generated %d article pages for lang=%s", len(articles), lang,
        )

    def _copy_images(self) -> None:
        """Copy visual assets to site/images/ directory.

        Preserves the source file extension (e.g. .jpg, .png) so that
        template references match the actual file on disk.
        """
        images_dir = SITE_DIR / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT va.image_path, va.article_id, a.country
                FROM visual_assets va
                JOIN articles a ON a.id = va.article_id
                """
            ).fetchall()
        finally:
            conn.close()

        copied = 0
        for row in rows:
            image_path = row["image_path"]
            if not image_path or image_path == "[placeholder]":
                continue
            src = Path(image_path)
            if not src.exists():
                continue
            country = row["country"]
            article_id = row["article_id"]
            ext = src.suffix or ".jpg"
            dest = images_dir / f"{country}-{article_id}{ext}"
            shutil.copy2(str(src), str(dest))
            copied += 1

        logger.info("Copied %d images to %s", copied, images_dir)

    # ------------------------------------------------------------------
    # Tool pages
    # ------------------------------------------------------------------

    # FAQ data for each tool page
    TOOL_FAQS: dict[str, dict[str, list[dict[str, str]]]] = {
        "tax-simulator": {
            "ja": [
                {"q": "UAEに個人所得税はありますか？", "a": "UAEでは個人所得税が課されることはありません。給与・投資利益・資産売却益のいずれも非課税となっています。ただし、2023年6月に導入された法人税（課税所得37.5万AED超に対して9%）や、2018年から適用されているVAT 5%は別途存在する点にご留意ください。"},
                {"q": "サウジアラビアの外国人に対する税金は？", "a": "個人所得税については、サウジアラビアも非課税を維持しています。一方で、外国法人には20%の法人税が適用され、ザカート（イスラム税）は自国民の法人に対して課されるのみとなります。VATは2020年に5%から15%へ引き上げられました。"},
                {"q": "日本の税金はどのように計算されますか？", "a": "日本の税負担は複数の要素で構成されています。まず所得税が累進課税方式で5〜45%、これに住民税10%と復興特別所得税2.1%が上乗せされます。さらに健康保険・年金などの社会保険料が給与の約15%を占めるため、年収1,500万円を超えると実効税率は50%に迫ることもあります。"},
            ],
            "en": [
                {"q": "Is there personal income tax in the UAE?", "a": "No — the UAE imposes zero personal income tax on salaries, investment gains, and capital gains. Note, however, that a 9% corporate tax (on taxable income exceeding AED 375K) took effect in June 2023, and a 5% VAT has been in place since 2018."},
                {"q": "What taxes apply to foreigners in Saudi Arabia?", "a": "Saudi Arabia does not levy personal income tax. Foreign-owned businesses are subject to a 20% corporate tax rate. VAT stands at 15% following the 2020 rate increase. Zakat applies only to Saudi-owned entities."},
                {"q": "How is Japan's tax calculated?", "a": "Japan's tax burden comprises multiple layers: progressive income tax (5–45%), a flat 10% resident tax, a 2.1% reconstruction surtax, and social insurance premiums of roughly 15% of salary. For earners above JPY 15M, the effective rate can approach 50%."},
            ],
            "ar": [
                {"q": "هل توجد ضريبة دخل شخصي في الإمارات؟", "a": "لا تفرض الإمارات أي ضريبة على الدخل الشخصي، سواء الرواتب أو أرباح الاستثمار. مع ذلك، تطبق ضريبة شركات بنسبة 9% وضريبة قيمة مضافة 5%."},
                {"q": "ما الضرائب المطبقة على الأجانب في السعودية؟", "a": "لا ضريبة دخل شخصي في المملكة. الشركات الأجنبية تخضع لضريبة 20%، وضريبة القيمة المضافة 15%."},
            ],
        },
        "golden-visa": {
            "ja": [
                {"q": "UAEゴールデンビザの有効期間は？", "a": "10年間有効で、条件を満たす限り更新が可能です。従来のビザと異なりスポンサー（雇用主）が不要で、UAE国外に6ヶ月以上滞在してもビザが失効しない点が大きなメリットとなっています。2022年の制度改正により、対象カテゴリも大幅に拡大されました。"},
                {"q": "サウジプレミアムレジデンシーの費用は？", "a": "2つのタイプから選択できます。永住型（Permanent）は80万SAR（約3,200万円）の一括支払いで取得でき、年次更新型（Renewable）は毎年10万SAR（約400万円）の支払いとなります。いずれもサウジ国内での不動産取得や事業活動が認められます。"},
                {"q": "ゴールデンビザで家族も滞在できますか？", "a": "もちろん可能です。配偶者と18歳未満の子供をスポンサーとして帯同でき、家族全員に同等の長期滞在ビザが発行されます。お子様の就学年齢についても、UAE国内のインターナショナルスクールへの入学手続きがスムーズに進められるようになっています。"},
            ],
            "en": [
                {"q": "How long is the UAE Golden Visa valid?", "a": "It lasts 10 years and is renewable provided eligibility conditions continue to be met. Unlike conventional visas, no employer sponsor is required, and the visa remains valid even during extended absences from the UAE. The 2022 reform significantly broadened eligible categories."},
                {"q": "What does Saudi Premium Residency cost?", "a": "Two options are available: a permanent residency for a one-time fee of SAR 800K (~$213K), or an annually renewable permit at SAR 100K (~$27K) per year. Both tiers grant the right to own property and operate businesses in Saudi Arabia."},
                {"q": "Can family members be included?", "a": "Absolutely. Holders may sponsor their spouse and children under 18, with each family member receiving their own long-term residence visa. This also facilitates enrollment at UAE international schools."},
            ],
            "ar": [
                {"q": "ما مدة صلاحية التأشيرة الذهبية الإماراتية؟", "a": "صالحة لمدة 10 سنوات وقابلة للتجديد دون الحاجة إلى كفيل. تبقى سارية حتى في حال الإقامة خارج الإمارات لفترات طويلة."},
                {"q": "ما تكلفة الإقامة المميزة السعودية؟", "a": "الإقامة الدائمة تكلف 800 ألف ريال دفعة واحدة. النوع السنوي يكلف 100 ألف ريال سنوياً. كلاهما يتيح تملك العقارات وممارسة الأعمال."},
            ],
        },
        "real-estate-roi": {
            "ja": [
                {"q": "ドバイの不動産利回りは？", "a": "直近のデータによると、ドバイの平均表面利回りは5〜8%に達しており、東京の3〜4%と比較すると明らかに高い水準にあります。中でもドバイ・マリーナやJVC（Jumeirah Village Circle）は安定した需要があり、投資家から根強い人気を集めています。"},
                {"q": "外国人でもドバイの不動産を購入できますか？", "a": "購入可能です。ドバイには政府指定のフリーホールドエリアが設けられており、外国人でも完全所有権（フリーホールド）で不動産を取得できます。代表的なエリアとしてはダウンタウン、マリーナ、パーム・ジュメイラなどが挙げられます。"},
                {"q": "キャップレートとROIの違いは？", "a": "どちらも投資効率を測る指標ですが、計算方法が異なります。キャップレートは物件価格に対するNOI（営業純利益）の比率で、物件同士の比較に適しています。一方、ROIは購入諸費用を含めた総投資額に対するリターンを示すため、実際の投資判断により近い指標といえます。"},
            ],
            "en": [
                {"q": "What is the average rental yield in Dubai?", "a": "Recent data shows Dubai's average gross yield at 5–8%, notably above Tokyo's 3–4%. Marina and JVC (Jumeirah Village Circle) attract consistent demand and remain investor favorites."},
                {"q": "Can foreigners buy property in Dubai?", "a": "Yes — within government-designated freehold zones, foreign nationals may acquire full ownership (freehold title). Key areas include Downtown, Marina, and Palm Jumeirah."},
                {"q": "What is the difference between cap rate and ROI?", "a": "Both gauge investment efficiency but differ in scope. Cap rate divides NOI by property price, ideal for comparing properties. ROI factors in total acquisition costs (fees, taxes, closing costs), offering a more realistic picture of actual investment returns."},
            ],
            "ar": [
                {"q": "ما متوسط العائد الإيجاري في دبي؟", "a": "يتراوح العائد الإجمالي في دبي بين 5-8%، متفوقاً بوضوح على طوكيو (3-4%). مناطق المارينا وJVC تحظى بطلب مستمر من المستثمرين."},
                {"q": "هل يمكن للأجانب شراء عقارات في دبي؟", "a": "نعم، في مناطق التملك الحر المحددة من الحكومة يمكن للأجانب الحصول على ملكية كاملة. تشمل المناطق الشهيرة داون تاون والمارينا ونخلة جميرا."},
            ],
        },
        "cost-of-living": {
            "ja": [
                {"q": "ドバイと東京、どちらが生活費が高い？", "a": "一概には言えず、生活水準によって答えが変わります。スタンダード水準であれば両都市はほぼ同等ですが、ラグジュアリー水準になるとドバイが東京を上回る傾向が見られます。特に差が顕著なのは住居費（ドバイの一等地は東京の1.5〜2倍）と教育費（インターナショナルスクール）の2項目です。"},
                {"q": "リヤドの生活費はドバイより安い？", "a": "全般的に20〜40%ほど安くなる傾向があります。最大の差は家賃で、同等グレードの住居でもリヤドはドバイの約半額というケースも珍しくありません。食費や交通費の差は比較的小さいものの、エンターテインメント関連の選択肢はドバイが圧倒的に多い点も考慮に入れるべきでしょう。"},
                {"q": "インターナショナルスクールの費用は？", "a": "ドバイでは年間100〜300万円、リヤドでは80〜250万円が一般的な目安となります。カリキュラム（IB / British / American）やスクールのランクによって大きく変動するため、複数校の比較検討をお勧めします。なお、一部の大手企業では教育手当として学費の全額または一部を負担するケースもあります。"},
            ],
            "en": [
                {"q": "Is Dubai or Tokyo more expensive?", "a": "The answer depends on lifestyle tier. At a standard level, overall costs are broadly comparable. At the luxury end, Dubai tends to be pricier — mainly due to prime-area rents (1.5–2x Tokyo) and international school fees."},
                {"q": "Is Riyadh cheaper than Dubai?", "a": "Generally 20–40% less across most categories. Housing shows the widest gap — similar-grade apartments in Riyadh can cost roughly half the Dubai equivalent. Food and transport differences are more modest, though Dubai offers significantly more entertainment options."},
                {"q": "How much do international schools cost?", "a": "Budget $27K–$80K per year in Dubai and $21K–$67K in Riyadh. Costs fluctuate considerably by curriculum (IB, British, American) and school tier, so comparing multiple options is advisable. Some multinational employers cover tuition as part of relocation packages."},
            ],
            "ar": [
                {"q": "أيهما أغلى، دبي أم طوكيو؟", "a": "يعتمد الأمر على مستوى المعيشة المختار. في المستوى القياسي تتشابه التكاليف إجمالاً. أما في المستوى الفاخر فتميل دبي لتكون أغلى، خاصة في الإيجارات والمدارس الدولية."},
                {"q": "هل الرياض أرخص من دبي؟", "a": "نعم، بنسبة 20-40% في معظم الفئات. الفرق الأكبر في الإيجارات حيث قد تصل تكلفة السكن المماثل في الرياض إلى نصف نظيره في دبي."},
            ],
        },
    }

    TOOL_PAGES: list[dict[str, Any]] = [
        {
            "template": "tools/tools-index.html",
            "slug": "tools/index.html",
            "title_ja": "海外移住シミュレーター",
            "title_en": "Relocation Simulators & Tools",
            "title_ar": "أدوات محاكاة الهجرة",
            "desc_ja": "UAE・サウジアラビアへの移住を検討する日本人投資家向け：税金シミュレーター、ゴールデンビザ診断、不動産ROI計算機、生活コスト比較",
            "desc_en": "Tax simulator, Golden Visa checker, Real Estate ROI calculator & cost of living comparison for Japanese investors",
            "desc_ar": "محاكي الضرائب وتشخيص التأشيرة الذهبية وحاسبة العائد العقاري ومقارنة تكاليف المعيشة",
            "faq_key": None,
            "priority": "0.8",
        },
        {
            "template": "tools/tax-simulator.html",
            "slug": "tools/tax-simulator.html",
            "title_ja": "税金シミュレーター — 日本 vs UAE vs サウジアラビア",
            "title_en": "Tax Simulator — Japan vs UAE vs Saudi Arabia",
            "title_ar": "محاكي الضرائب — اليابان مقابل الإمارات والسعودية",
            "desc_ja": "年収を入力して日本・UAE・サウジアラビアの税負担を比較。移住による節税額をシミュレーション。",
            "desc_en": "Compare tax burdens across Japan, UAE & Saudi Arabia by annual income. Simulate potential tax savings from relocation.",
            "desc_ar": "قارن الأعباء الضريبية بين اليابان والإمارات والسعودية",
            "faq_key": "tax-simulator",
            "priority": "0.9",
        },
        {
            "template": "tools/golden-visa.html",
            "slug": "tools/golden-visa.html",
            "title_ja": "ゴールデンビザ診断 — UAE・サウジアラビア",
            "title_en": "Golden Visa Eligibility Checker — UAE & Saudi Arabia",
            "title_ar": "تشخيص التأشيرة الذهبية — الإمارات والسعودية",
            "desc_ja": "あなたの資産・職種・投資額からUAEゴールデンビザ・サウジプレミアムレジデンシーの取得可能性を診断。",
            "desc_en": "Check your eligibility for UAE Golden Visa & Saudi Premium Residency based on assets, occupation & investment.",
            "desc_ar": "تحقق من أهليتك للحصول على التأشيرة الذهبية الإماراتية والإقامة المميزة السعودية",
            "faq_key": "golden-visa",
            "priority": "0.9",
        },
        {
            "template": "tools/real-estate-roi.html",
            "slug": "tools/real-estate-roi.html",
            "title_ja": "不動産ROI計算機 — ドバイ vs 東京",
            "title_en": "Real Estate ROI Calculator — Dubai vs Tokyo",
            "title_ar": "حاسبة عائد الاستثمار العقاري — دبي مقابل طوكيو",
            "desc_ja": "ドバイ・東京の不動産投資リターンを比較。キャッシュフロー、キャップレート、5年/10年の資産推移を計算。",
            "desc_en": "Compare real estate investment returns in Dubai vs Tokyo. Calculate cash flow, cap rate & 10-year projections.",
            "desc_ar": "قارن عوائد الاستثمار العقاري بين دبي وطوكيو",
            "faq_key": "real-estate-roi",
            "priority": "0.9",
        },
        {
            "template": "tools/cost-of-living.html",
            "slug": "tools/cost-of-living.html",
            "title_ja": "生活コスト比較 — 東京 vs ドバイ vs リヤド",
            "title_en": "Cost of Living Comparison — Tokyo vs Dubai vs Riyadh",
            "title_ar": "مقارنة تكاليف المعيشة — طوكيو ودبي والرياض",
            "desc_ja": "東京・ドバイ・リヤドの生活費をカテゴリ別に比較。スタンダードからラグジュアリーまで3段階の生活水準で比較。",
            "desc_en": "Compare living costs across Tokyo, Dubai & Riyadh by category. Three lifestyle tiers from standard to luxury.",
            "desc_ar": "قارن تكاليف المعيشة بين طوكيو ودبي والرياض",
            "faq_key": "cost-of-living",
            "priority": "0.9",
        },
    ]

    def _generate_tool_pages(self, lang: str = "ja") -> None:
        """Generate interactive tool pages for the given language."""
        for page_info in self.TOOL_PAGES:
            template = self.env.get_template(page_info["template"])

            if lang == "ja":
                base_path = "../"
                rel_path = page_info["slug"]
            else:
                base_path = "../../"
                rel_path = f"{lang}/{page_info['slug']}"

            # Choose localised title/desc
            title = page_info.get(f"title_{lang}", page_info["title_en"])
            description = page_info.get(f"desc_{lang}", page_info["desc_en"])

            now_iso = self._iso_date(None)
            breadcrumbs = self._make_breadcrumbs([
                ("ホーム" if lang == "ja" else ("الرئيسية" if lang == "ar" else "Home"),
                 "" if lang == "ja" else f"{lang}/"),
                ("ツール" if lang == "ja" else ("الأدوات" if lang == "ar" else "Tools"),
                 "tools/" if lang == "ja" else f"{lang}/tools/"),
            ])

            # FAQ items
            faq_items: list[dict[str, str]] = []
            faq_key = page_info.get("faq_key")
            if faq_key and faq_key in self.TOOL_FAQS:
                faq_items = self.TOOL_FAQS[faq_key].get(lang, self.TOOL_FAQS[faq_key].get("en", []))

            html = template.render(
                title=title,
                description=description,
                lang=lang,
                base_path=base_path,
                lang_path=self._lang_path(rel_path, lang),
                countries=COUNTRIES,
                current_country=None,
                genres=self.genres_config,
                regions=None,
                current_region=None,
                current_genre=None,
                site_url=SITE_URL,
                canonical_url=f"{SITE_URL}/{rel_path}",
                page_type="website",
                breadcrumbs=breadcrumbs,
                published_date_iso=now_iso,
                modified_date_iso=now_iso,
                faq_items=faq_items,
                current_year=self._current_year(),
            )
            self._write_html(rel_path, html)
            self._generated_pages.append(
                {"rel_path": rel_path, "priority": page_info.get("priority", "0.8"), "changefreq": "monthly"},
            )

        logger.info("Generated tool pages for lang=%s", lang)

    # ------------------------------------------------------------------
    # Sitemap & robots.txt
    # ------------------------------------------------------------------

    def _generate_sitemap(self) -> None:
        """Generate sitemap.xml from all pages tracked during generation."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines: list[str] = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
            '        xmlns:xhtml="http://www.w3.org/1999/xhtml">',
        ]

        # Group pages by their base path (without language prefix) to build
        # hreflang alternate links.  Japanese pages have no prefix; en/ and
        # ar/ pages share the same base path after stripping the lang prefix.
        # Build a mapping: base_rel_path -> {lang: full_rel_path}
        lang_map: dict[str, dict[str, str]] = {}
        for page in self._generated_pages:
            rp = page["rel_path"]
            if rp.startswith("en/"):
                base = rp[3:]
                lang = "en"
            elif rp.startswith("ar/"):
                base = rp[3:]
                lang = "ar"
            else:
                base = rp
                lang = "ja"
            lang_map.setdefault(base, {})[lang] = rp

        for page in self._generated_pages:
            rp = page["rel_path"]
            loc = xml_escape(f"{SITE_URL}/{rp}")
            lines.append("  <url>")
            lines.append(f"    <loc>{loc}</loc>")
            lines.append(f"    <lastmod>{today}</lastmod>")
            lines.append(f"    <changefreq>{page['changefreq']}</changefreq>")
            lines.append(f"    <priority>{page['priority']}</priority>")

            # Determine the base path for hreflang alternates
            if rp.startswith("en/"):
                base = rp[3:]
            elif rp.startswith("ar/"):
                base = rp[3:]
            else:
                base = rp

            alternates = lang_map.get(base, {})
            for alt_lang in ["ja", "en", "ar"]:
                if alt_lang in alternates:
                    alt_href = xml_escape(f"{SITE_URL}/{alternates[alt_lang]}")
                    lines.append(
                        f'    <xhtml:link rel="alternate" hreflang="{alt_lang}" href="{alt_href}"/>',
                    )

            lines.append("  </url>")

        lines.append("</urlset>")

        sitemap_path = SITE_DIR / "sitemap.xml"
        sitemap_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Generated sitemap.xml with %d URLs", len(self._generated_pages))

    def _generate_robots_txt(self) -> None:
        """Generate robots.txt in the site output directory."""
        content = (
            "User-agent: *\n"
            "Allow: /\n"
            f"Sitemap: {SITE_URL}/sitemap.xml\n"
        )
        robots_path = SITE_DIR / "robots.txt"
        robots_path.write_text(content, encoding="utf-8")
        logger.info("Generated robots.txt")

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    @staticmethod
    def _current_year() -> str:
        """Return the current year as a string."""
        return str(datetime.now(timezone.utc).year)

    def generate_all(self) -> None:
        """Generate the complete static site."""
        logger.info("=== Static Site Generation START ===")

        # Reset page tracker for sitemap
        self._generated_pages = []

        # Migrate old 'dubai' entries to 'uae'
        conn = self._get_conn()
        try:
            conn.execute("UPDATE news_items SET country = 'uae' WHERE country = 'dubai'")
            conn.execute("UPDATE articles SET country = 'uae' WHERE country = 'dubai'")
            conn.commit()
            logger.info("Migrated 'dubai' entries to 'uae' in database.")
        finally:
            conn.close()

        for lang in ["ja", "en", "ar"]:
            self._generate_index(lang)
            self._generate_country_pages(lang)
            self._generate_article_pages(lang)
            self._generate_tool_pages(lang)

        self._copy_images()
        self._generate_sitemap()
        self._generate_robots_txt()

        # Count generated HTML files (exclude templates)
        html_files = list(SITE_DIR.rglob("*.html"))
        html_files = [f for f in html_files if "templates" not in str(f)]
        logger.info("Generated %d HTML pages.", len(html_files))
        logger.info("=== Static Site Generation COMPLETE ===")


# ---------------------------------------------------------------------------
# Standalone execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    generator = SiteGenerator()
    generator.generate_all()
