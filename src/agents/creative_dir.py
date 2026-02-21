"""Creative Director agent — generates image prompts and visuals for Connect-Sekai."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.api.gemini_client import GeminiClient
from src.api.imagen_client import ImagenClient, ImageSize

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = _PROJECT_ROOT / "config" / "countries.yaml"
IMAGES_ROOT = _PROJECT_ROOT / "data" / "images"

# ---------------------------------------------------------------------------
# Country-specific visual style guides
# ---------------------------------------------------------------------------
VISUAL_STYLES: dict[str, dict[str, Any]] = {
    "dubai": {
        "keywords": [
            "luxurious Dubai skyline at golden hour",
            "penthouse terrace overlooking Burj Khalifa",
            "private desert dinner under the stars",
            "sleek Marina yacht deck at sunset",
            "opulent gold-accented interior lounge",
        ],
        "color_palette": "warm golds, deep navy, champagne tones",
        "mood": "aspirational, sophisticated, cosmopolitan wealth",
    },
    "saudi": {
        "keywords": [
            "Al-Ula ancient rock formations at dawn",
            "NEOM futuristic cityscape concept",
            "traditional Najdi architecture with modern lighting",
            "Diriyah heritage quarter blending old and new",
            "Vision 2030 innovation hub interior",
        ],
        "color_palette": "desert sand, emerald green, pearl white",
        "mood": "visionary, culturally rooted, forward-looking",
    },
    "brunei": {
        "keywords": [
            "Sultan Omar Ali Saifuddien Mosque reflected at dusk",
            "tropical rainforest canopy with golden sunlight",
            "royal Istana Nurul Iman palace garden",
            "traditional Malay craft with gold leaf detail",
            "Kampong Ayer water village at twilight",
        ],
        "color_palette": "royal gold, lush green, ivory white",
        "mood": "serene opulence, tropical majesty, timeless elegance",
    },
}

# Brand-level prompt guidelines applied to every image
BRAND_RULES = (
    "Style: premium editorial photography, cinematic lighting, subtle depth of field. "
    "Brand: Connect-Sekai — bridging Japan and the world. "
    "No text overlays, no watermarks, no logos. "
    "Clean composition with generous negative space for later text placement. "
    "High resolution, photorealistic."
)

FOMUS_VISUAL_RULES = (
    "Include a beautifully crafted Japanese masu (wooden sake cup) used as "
    "a refined interior accent or tea ceremony element. "
    "The masu should appear natural in the scene — placed on a low wooden table, "
    "beside a matcha bowl, or as an elegant desk accessory. "
    "No alcohol imagery."
)


class CreativeDirector:
    """Generates brand-consistent image prompts and produces visuals."""

    def __init__(
        self,
        config_path: Path = CONFIG_PATH,
        images_root: Path = IMAGES_ROOT,
    ) -> None:
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.countries: dict[str, dict[str, Any]] = self.config.get("countries", {})
        self.fomus_config: dict[str, Any] = self.config.get("fomus", {})
        self.images_root = images_root
        self.gemini = GeminiClient()
        self.imagen = ImagenClient()

    # ------------------------------------------------------------------
    # Prompt generation
    # ------------------------------------------------------------------
    def build_image_prompt(
        self,
        article: dict[str, Any],
        include_fomus: bool = False,
    ) -> str:
        """Build an image-generation prompt from article data.

        Args:
            article: An article dict (output of TrendAnalyst or Copywriter).
                     Expected keys: country, title, summary (or investor_score.angle).
            include_fomus: Whether to incorporate FOMUS masu visuals.

        Returns:
            A fully-formed image prompt string.
        """
        country_key: str = article.get("country", "dubai")
        style = VISUAL_STYLES.get(country_key, VISUAL_STYLES["dubai"])

        title = article.get("title", "")
        summary_text = ""
        if isinstance(article.get("summary"), dict):
            summary_text = article["summary"].get("summary", "")
        elif isinstance(article.get("summary"), str):
            summary_text = article["summary"]

        angle = ""
        score_data = article.get("investor_score", {})
        if isinstance(score_data, dict):
            angle = score_data.get("angle", "")

        content_type = ""
        if isinstance(score_data, dict):
            content_type = score_data.get("content_type", "")

        # Ask Gemini to craft an optimal visual prompt
        meta_prompt = (
            "You are a world-class creative director for a luxury media brand called Connect-Sekai.\n"
            "Generate a single, detailed image-generation prompt (in English) for a social media visual.\n\n"
            f"Article title: {title}\n"
            f"Summary: {summary_text}\n"
            f"Suggested angle: {angle}\n"
            f"Content type: {content_type}\n"
            f"Country/Region: {country_key}\n"
            f"Visual style keywords: {', '.join(style['keywords'])}\n"
            f"Color palette: {style['color_palette']}\n"
            f"Mood: {style['mood']}\n"
            f"Brand rules: {BRAND_RULES}\n"
        )
        if include_fomus:
            meta_prompt += f"FOMUS integration: {FOMUS_VISUAL_RULES}\n"

        meta_prompt += (
            "\nReturn ONLY a JSON object with these keys:\n"
            '{"prompt": "the full image generation prompt", '
            '"rationale": "1-sentence explanation of the visual direction"}'
        )

        result = self.gemini._call_json(
            meta_prompt,
            fallback={
                "prompt": self._fallback_prompt(country_key, title, include_fomus),
                "rationale": "Fallback prompt based on country visual style.",
            },
        )
        return result.get("prompt", self._fallback_prompt(country_key, title, include_fomus))

    def _fallback_prompt(
        self,
        country_key: str,
        title: str,
        include_fomus: bool,
    ) -> str:
        """Build a deterministic fallback prompt when Gemini is unavailable."""
        style = VISUAL_STYLES.get(country_key, VISUAL_STYLES["dubai"])
        base = (
            f"{style['keywords'][0]}. {style['mood']}. "
            f"Color palette: {style['color_palette']}. "
            f"Context: {title}. "
            f"{BRAND_RULES}"
        )
        if include_fomus:
            base += f" {FOMUS_VISUAL_RULES}"
        return base

    # ------------------------------------------------------------------
    # Image generation & saving
    # ------------------------------------------------------------------
    def generate_visuals(
        self,
        article: dict[str, Any],
        sizes: list[ImageSize] | None = None,
        include_fomus: bool = False,
    ) -> list[Path]:
        """Generate images for an article across specified sizes.

        Args:
            article: Article data dict.
            sizes: List of target sizes. Defaults to Instagram square.
            include_fomus: Whether to add FOMUS masu imagery.

        Returns:
            List of paths to the saved images.
        """
        if sizes is None:
            sizes = ["1080x1080"]

        country_key = article.get("country", "dubai")
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        save_dir = self.images_root / country_key / date_str

        prompt = self.build_image_prompt(article, include_fomus=include_fomus)
        logger.info("Image prompt for [%s]: %s", country_key, prompt[:120])

        saved_paths: list[Path] = []
        for size in sizes:
            slug = _slugify(article.get("title", "image"))
            filename = f"{slug}_{size}.png"
            dest = save_dir / filename

            try:
                path = self.imagen.generate_and_save(prompt, dest, size=size)
                saved_paths.append(path)
                logger.info("Generated %s image: %s", size, path)
            except RuntimeError as e:
                logger.error("Image generation failed (%s, %s): %s", country_key, size, e)

        return saved_paths

    def process_articles(
        self,
        articles: dict[str, list[dict[str, Any]]],
        top_n: int = 3,
        sizes: list[ImageSize] | None = None,
    ) -> dict[str, list[Path]]:
        """Process top articles per country and generate images.

        Args:
            articles: {country_key: [article, ...]} from TrendAnalyst output.
            top_n: Number of top-scoring articles to visualize per country.
            sizes: Image sizes to generate.

        Returns:
            {country_key: [saved_image_paths]}
        """
        if sizes is None:
            sizes = ["1080x1080", "1080x1350"]

        fomus_ratio = self.fomus_config.get("appearance_ratio", 0.2)
        results: dict[str, list[Path]] = {}

        for country_key, article_list in articles.items():
            results[country_key] = []
            selected = article_list[:top_n]

            for idx, article in enumerate(selected):
                # Determine FOMUS inclusion based on configured ratio
                include_fomus = self._should_include_fomus(idx, len(selected), fomus_ratio)

                paths = self.generate_visuals(
                    article,
                    sizes=sizes,
                    include_fomus=include_fomus,
                )
                results[country_key].extend(paths)

        return results

    @staticmethod
    def _should_include_fomus(index: int, total: int, ratio: float) -> bool:
        """Determine whether a given article index should include FOMUS visuals."""
        if total == 0 or ratio <= 0:
            return False
        # Include FOMUS for the last N articles proportional to the ratio
        fomus_count = max(1, round(total * ratio))
        return index >= total - fomus_count


def _slugify(text: str, max_len: int = 50) -> str:
    """Create a filesystem-safe slug from text."""
    import re
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:max_len] if slug else "untitled"


# ------------------------------------------------------------------
# CLI entry point for testing
# ------------------------------------------------------------------
def main() -> None:
    """Test run: generate an image for a sample article per country."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    director = CreativeDirector()

    # Sample articles to test with (mimics TrendAnalyst output structure)
    sample_articles: dict[str, list[dict[str, Any]]] = {
        "dubai": [
            {
                "country": "dubai",
                "title": "Dubai launches new Golden Visa incentives for tech entrepreneurs",
                "summary": {"summary": "ドバイがテック起業家向けゴールデンビザの新優遇策を発表"},
                "investor_score": {
                    "score": 85,
                    "angle": "日本のスタートアップがドバイ進出するチャンス",
                    "content_type": "business",
                },
            },
        ],
        "saudi": [
            {
                "country": "saudi",
                "title": "NEOM announces Japanese garden district in The Line",
                "summary": {"summary": "NEOMのザ・ライン内に日本庭園地区の建設を発表"},
                "investor_score": {
                    "score": 92,
                    "angle": "日本の造園技術が中東メガプロジェクトに採用",
                    "content_type": "culture",
                },
            },
        ],
        "brunei": [
            {
                "country": "brunei",
                "title": "Brunei royal family commissions Japanese lacquerware collection",
                "summary": {"summary": "ブルネイ王室が日本の漆器コレクションを特注"},
                "investor_score": {
                    "score": 78,
                    "angle": "伝統工芸の海外王室向け高級マーケット",
                    "content_type": "culture",
                },
            },
        ],
    }

    print("\n=== Connect-Sekai Creative Director — Test Run ===\n")

    for country_key, articles in sample_articles.items():
        article = articles[0]
        print(f"\n--- {country_key.upper()} ---")
        print(f"  Article: {article['title']}")

        # Build prompt only (skip actual image generation in dry-run)
        prompt = director.build_image_prompt(article, include_fomus=False)
        print(f"  Prompt:  {prompt[:200]}...")

        fomus_prompt = director.build_image_prompt(article, include_fomus=True)
        print(f"  FOMUS:   {fomus_prompt[:200]}...")

        # To actually generate images, uncomment the following:
        # paths = director.generate_visuals(article, sizes=["1080x1080"])
        # print(f"  Saved:   {paths}")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
