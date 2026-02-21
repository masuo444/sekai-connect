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
                og_image=f"images/{country_key}-{article['id']}{article.get('image_ext', '.jpg')}",
                lang=lang,
                base_path=base_path,
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
                {"q": "UAEに個人所得税はありますか？", "a": "いいえ。UAEでは個人所得税は課されません。ただし、法人税（課税所得37.5万AED超に9%）やVAT（5%）は存在します。"},
                {"q": "サウジアラビアの外国人に対する税金は？", "a": "サウジアラビアでも個人所得税はありませんが、外国法人は20%の法人税が課されます。また、VAT 15%が適用されます。"},
                {"q": "日本の税金はどのように計算されますか？", "a": "日本の所得税は累進課税（5〜45%）に住民税10%、復興特別所得税2.1%、社会保険料約15%が加わります。"},
            ],
            "en": [
                {"q": "Is there personal income tax in the UAE?", "a": "No. The UAE does not levy personal income tax. However, corporate tax (9% on taxable income over AED 375K) and VAT (5%) exist."},
                {"q": "What taxes apply to foreigners in Saudi Arabia?", "a": "Saudi Arabia has no personal income tax, but foreign companies face 20% corporate tax. VAT is 15%."},
                {"q": "How is Japan's tax calculated?", "a": "Japan applies progressive income tax (5-45%), plus 10% resident tax, 2.1% surtax, and approximately 15% social insurance."},
            ],
            "ar": [
                {"q": "هل توجد ضريبة دخل شخصي في الإمارات؟", "a": "لا. لا تفرض الإمارات ضريبة دخل شخصي، لكن توجد ضريبة شركات (9%) وضريبة القيمة المضافة (5%)."},
                {"q": "ما الضرائب المطبقة على الأجانب في السعودية؟", "a": "لا توجد ضريبة دخل شخصي في السعودية، لكن الشركات الأجنبية تخضع لضريبة 20%."},
            ],
        },
        "golden-visa": {
            "ja": [
                {"q": "UAEゴールデンビザの有効期間は？", "a": "UAEゴールデンビザは10年間有効で、更新可能です。スポンサー不要で、UAE国外での長期滞在も可能です。"},
                {"q": "サウジプレミアムレジデンシーの費用は？", "a": "永住型は80万SAR（約3,200万円）の一括支払い、年次更新型は年間10万SAR（約400万円）です。"},
                {"q": "ゴールデンビザで家族も滞在できますか？", "a": "はい。配偶者と子供（18歳未満）をスポンサーでき、家族全員に長期滞在ビザが発行されます。"},
            ],
            "en": [
                {"q": "How long is the UAE Golden Visa valid?", "a": "The UAE Golden Visa is valid for 10 years and is renewable. It does not require a sponsor and allows long-term stays outside the UAE."},
                {"q": "What does Saudi Premium Residency cost?", "a": "The permanent type costs SAR 800K (~$213K) as a one-time payment. The annual type costs SAR 100K (~$27K) per year."},
                {"q": "Can family members be included?", "a": "Yes. You can sponsor your spouse and children under 18, and they will receive long-term residence visas."},
            ],
            "ar": [
                {"q": "ما مدة صلاحية التأشيرة الذهبية الإماراتية؟", "a": "التأشيرة الذهبية صالحة لمدة 10 سنوات وقابلة للتجديد."},
                {"q": "ما تكلفة الإقامة المميزة السعودية؟", "a": "النوع الدائم يكلف 800 ألف ريال، والنوع السنوي 100 ألف ريال سنوياً."},
            ],
        },
        "real-estate-roi": {
            "ja": [
                {"q": "ドバイの不動産利回りは？", "a": "ドバイの平均表面利回りは5〜8%で、東京（3〜4%）と比較して高い水準です。特にマリーナやJVCエリアが人気です。"},
                {"q": "外国人でもドバイの不動産を購入できますか？", "a": "はい。フリーホールドエリアでは外国人も完全所有権で不動産を購入できます。"},
                {"q": "キャップレートとROIの違いは？", "a": "キャップレートは物件価格に対するNOIの割合、ROIは購入諸費用を含めた総投資額に対するリターンです。"},
            ],
            "en": [
                {"q": "What is the average rental yield in Dubai?", "a": "Dubai's average gross yield is 5-8%, higher than Tokyo's 3-4%. Marina and JVC areas are particularly popular."},
                {"q": "Can foreigners buy property in Dubai?", "a": "Yes. Foreigners can purchase freehold property in designated freehold areas with full ownership rights."},
                {"q": "What is the difference between cap rate and ROI?", "a": "Cap rate measures NOI relative to property price. ROI includes all purchase costs in the total investment calculation."},
            ],
            "ar": [
                {"q": "ما متوسط العائد الإيجاري في دبي؟", "a": "يتراوح العائد الإجمالي في دبي بين 5-8%، وهو أعلى من طوكيو (3-4%)."},
                {"q": "هل يمكن للأجانب شراء عقارات في دبي؟", "a": "نعم. يمكن للأجانب شراء عقارات بملكية حرة في المناطق المخصصة."},
            ],
        },
        "cost-of-living": {
            "ja": [
                {"q": "ドバイと東京、どちらが生活費が高い？", "a": "生活水準によります。スタンダード水準ではほぼ同等ですが、ラグジュアリー水準ではドバイの方が高くなる傾向があります。特に家賃と教育費に差が出ます。"},
                {"q": "リヤドの生活費はドバイより安い？", "a": "はい。リヤドはドバイに比べて全般的に20〜40%安い傾向があります。特に家賃が大きな差となります。"},
                {"q": "インターナショナルスクールの費用は？", "a": "ドバイのインターナショナルスクールは年間100〜300万円、リヤドは80〜250万円が目安です。"},
            ],
            "en": [
                {"q": "Is Dubai or Tokyo more expensive?", "a": "It depends on lifestyle. At standard levels they are similar, but luxury living tends to be pricier in Dubai, especially rent and education."},
                {"q": "Is Riyadh cheaper than Dubai?", "a": "Yes. Riyadh is generally 20-40% cheaper than Dubai across most categories, particularly rent."},
                {"q": "How much do international schools cost?", "a": "Dubai international schools range from $27K-$80K per year, while Riyadh ranges from $21K-$67K."},
            ],
            "ar": [
                {"q": "أيهما أغلى، دبي أم طوكيو؟", "a": "يعتمد على نمط الحياة. في المستوى القياسي متشابهان، لكن الحياة الفاخرة أغلى في دبي."},
                {"q": "هل الرياض أرخص من دبي؟", "a": "نعم. الرياض أرخص بنسبة 20-40% في معظم الفئات."},
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
