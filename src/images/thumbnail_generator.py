"""AI photo thumbnail generator for Connect-Sekai articles.

Generates 1200x630 OGP-standard thumbnails using Nano Banana Pro
(gemini-3-pro-image-preview). No text overlay — photo only for
language-neutral accessibility.
Falls back to gradient backgrounds if photo generation fails.
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image, ImageDraw

load_dotenv()

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Image dimensions (OGP standard)
# ---------------------------------------------------------------------------

WIDTH = 1200
HEIGHT = 630

# ---------------------------------------------------------------------------
# Country-specific colour schemes (used for gradient fallback only)
# ---------------------------------------------------------------------------

COUNTRY_THEMES: dict[str, dict[str, Any]] = {
    "uae": {
        "gradient_start": (10, 15, 40),
        "gradient_end": (212, 175, 55),
    },
    "saudi": {
        "gradient_start": (0, 61, 31),
        "gradient_end": (0, 108, 53),
    },
    "brunei": {
        "gradient_start": (10, 15, 40),
        "gradient_end": (247, 224, 23),
    },
    "japan": {
        "gradient_start": (10, 15, 40),
        "gradient_end": (139, 0, 0),
    },
}

# ---------------------------------------------------------------------------
# Country-specific photo context for AI image generation prompts
# ---------------------------------------------------------------------------

COUNTRY_PHOTO_CONTEXT: dict[str, list[str]] = {
    "uae": [
        "Dubai Marina waterfront at golden hour, yachts and towers",
        "Abu Dhabi Grand Mosque at twilight, reflecting pools",
        "Dubai Creek with traditional dhow boats, old town contrast",
        "Burj Khalifa seen from desert dunes at sunset",
        "Palm Jumeirah aerial view, turquoise water, tropical",
        "Dubai Frame with city panorama, dramatic clouds",
        "Abu Dhabi Louvre museum exterior, water reflections",
        "Dubai old souks, spice market, warm lantern light",
    ],
    "saudi": [
        "AlUla ancient tombs at golden hour, dramatic rock formations",
        "Riyadh Kingdom Tower at night, modern skyline",
        "Jeddah historic Al-Balad district, coral stone buildings",
        "Red Sea coast turquoise water, pristine beach, Saudi Arabia",
        "Edge of the World cliff near Riyadh, vast desert panorama",
        "Diriyah heritage site, traditional Najdi architecture",
    ],
    "brunei": [
        "Sultan Omar Ali Saifuddien Mosque at sunset, water village",
        "Brunei rainforest canopy, Temburong National Park",
        "Kampong Ayer water village, traditional stilt houses",
        "Brunei Empire Hotel exterior, tropical luxury resort",
        "Mangrove river in Brunei, proboscis monkeys, lush green",
    ],
    "japan": [
        "Tokyo Tower at dusk, cherry blossoms in foreground",
        "Shibuya crossing from above, neon glow, rain reflections",
        "Kyoto bamboo grove, soft morning light, zen atmosphere",
        "Mount Fuji at sunrise from Lake Kawaguchi, mirror reflection",
        "Akihabara electric town at night, colorful anime signs",
        "Traditional Japanese garden with autumn maple leaves",
        "Osaka Dotonbori canal at night, vibrant lights",
        "Shinjuku skyscrapers at blue hour, moody atmosphere",
    ],
}


# ---------------------------------------------------------------------------
# AI photo generation (Nano Banana Pro)
# ---------------------------------------------------------------------------

def _summarize_title(title: str, max_len: int = 50) -> str:
    """Compress an article title to ~50 chars for better prompt quality."""
    if len(title) <= max_len:
        return title
    return title[:max_len] + "..."


def _generate_photo(title: str, country: str, genre: str) -> Optional[Image.Image]:
    """Generate a photo using Nano Banana Pro (gemini-3-pro-image-preview).

    Args:
        title: Article title (used to build prompt).
        country: Country key for scene context.
        genre: Article genre for additional context.

    Returns:
        PIL Image or None if generation fails.
    """
    scenes = COUNTRY_PHOTO_CONTEXT.get(country, ["modern cityscape at golden hour"])
    # Pick a scene based on title hash so each article gets a different scene
    scene = scenes[hash(title) % len(scenes)]
    title_summary = _summarize_title(title)

    prompt = (
        f"Cinematic photograph: {scene}. "
        f"The mood should evoke: {title_summary}. "
        f"Style: editorial magazine cover, atmospheric, "
        f"vivid colors, beautiful scenery, wide landscape ratio. "
        f"NOT a corporate/business illustration. No people in suits. "
        f"No text, no watermarks, no logos, no UI elements."
    )

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("GOOGLE_API_KEY not set, using gradient fallback")
        return None

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3-pro-image-preview",
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        for part in response.parts:
            if part.inline_data is not None:
                genai_image = part.as_image()
                photo = Image.open(io.BytesIO(genai_image.image_bytes))
                logger.info("Nano Banana Pro photo generated (%dx%d)", photo.width, photo.height)
                return photo

        logger.warning("Nano Banana Pro returned no image data, using gradient fallback")
        return None

    except Exception as e:
        logger.warning("Nano Banana Pro generation failed, using gradient fallback: %s", e)
        return None


def _center_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize and center-crop an image to the exact target dimensions."""
    src_w, src_h = img.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        new_h = target_h
        new_w = int(src_w * (target_h / src_h))
    else:
        new_w = target_w
        new_h = int(src_h * (target_w / src_w))

    img = img.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


# ---------------------------------------------------------------------------
# Drawing helpers (gradient fallback only)
# ---------------------------------------------------------------------------

def _draw_gradient_fast(img: Image.Image, start: tuple, end: tuple) -> None:
    """Draw a diagonal gradient using horizontal-line averaging for speed."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for y in range(h):
        t_left = y / (w + h)
        t_right = (w + y) / (w + h)
        t = (t_left + t_right) / 2.0
        r = int(start[0] + (end[0] - start[0]) * t)
        g = int(start[1] + (end[1] - start[1]) * t)
        b = int(start[2] + (end[2] - start[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------

def generate_thumbnail(
    title: str,
    country: str,
    genre: str = "business",
    article_id: Optional[int] = None,
    output_path: Optional[Path] = None,
) -> Path:
    """Generate an article thumbnail image (photo only, no text).

    Uses Nano Banana Pro to generate a photo matching the article content.
    Falls back to gradient background if photo generation fails.

    Args:
        title: Article title (used for AI prompt).
        country: Country key (uae, saudi, brunei, japan).
        genre: Genre key for prompt context.
        article_id: Article ID (used for default filename).
        output_path: Where to save; if None, uses default data/images/{country}/ path.

    Returns:
        Path to the generated JPEG image.
    """
    theme = COUNTRY_THEMES.get(country, COUNTRY_THEMES["uae"])

    # Determine output path
    if output_path is None:
        if article_id is None:
            raise ValueError("Either output_path or article_id must be provided")
        output_dir = _ROOT / "data" / "images" / country
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"article-{article_id}.jpg"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # --- Generate AI photo or fallback to gradient ---
    photo = _generate_photo(title, country, genre)

    if photo is not None:
        img = _center_crop(photo.convert("RGB"), WIDTH, HEIGHT)
    else:
        img = Image.new("RGB", (WIDTH, HEIGHT))
        _draw_gradient_fast(img, theme["gradient_start"], theme["gradient_end"])

    # --- Save (photo only, no text overlay) ---
    img.save(str(output_path), "JPEG", quality=85, optimize=True)
    logger.info("Generated thumbnail: %s", output_path)

    return output_path


# ---------------------------------------------------------------------------
# Convenience: classify genre from article data
# ---------------------------------------------------------------------------

def classify_genre(title: str, body: str, genres_config: dict[str, Any]) -> str:
    """Classify an article into a genre based on keyword matching."""
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
