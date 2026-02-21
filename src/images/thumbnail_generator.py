"""PIL-based thumbnail generator for Connect-Sekai articles.

Generates professional, branded 1200x630 OGP-standard thumbnails
with country-specific gradients, geometric patterns, and Japanese text.
"""

from __future__ import annotations

import logging
import math
import platform
import textwrap
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Image dimensions (OGP standard)
# ---------------------------------------------------------------------------

WIDTH = 1200
HEIGHT = 630

# ---------------------------------------------------------------------------
# Country-specific colour schemes
# ---------------------------------------------------------------------------

COUNTRY_THEMES: dict[str, dict[str, Any]] = {
    "uae": {
        "gradient_start": (10, 15, 40),       # #0A0F28 dark navy
        "gradient_end": (212, 175, 55),        # #D4AF37 gold
        "accent": (212, 175, 55),              # gold
        "accent_dark": (160, 130, 30),         # darker gold for badge bg
        "badge_bg": (212, 175, 55),
        "badge_text": (10, 15, 40),
        "label": "UAE",
    },
    "saudi": {
        "gradient_start": (0, 61, 31),         # #003D1F dark green
        "gradient_end": (0, 108, 53),          # #006C35 emerald
        "accent": (255, 255, 255),             # white
        "accent_dark": (0, 80, 40),
        "badge_bg": (255, 255, 255),
        "badge_text": (0, 61, 31),
        "label": "SAUDI",
    },
    "brunei": {
        "gradient_start": (10, 15, 40),        # #0A0F28 dark navy
        "gradient_end": (247, 224, 23),         # #F7E017 yellow
        "accent": (247, 224, 23),              # yellow
        "accent_dark": (190, 170, 10),
        "badge_bg": (247, 224, 23),
        "badge_text": (10, 15, 40),
        "label": "BRUNEI",
    },
    "japan": {
        "gradient_start": (10, 15, 40),        # #0A0F28 dark navy
        "gradient_end": (139, 0, 0),           # #8B0000 deep red
        "accent": (188, 0, 45),                # #BC002D Japan red
        "accent_dark": (140, 0, 30),
        "badge_bg": (188, 0, 45),
        "badge_text": (255, 255, 255),
        "label": "JAPAN",
    },
}

# Default genre labels (Japanese)
GENRE_LABELS: dict[str, str] = {
    "business": "ビジネス",
    "real-estate": "不動産",
    "lifestyle": "ライフスタイル",
    "culture": "文化",
    "technology": "テクノロジー",
    "entertainment": "エンタメ",
}

# ---------------------------------------------------------------------------
# Font discovery
# ---------------------------------------------------------------------------

_FONT_CACHE: dict[str, Optional[str]] = {}


def _find_font(weight: str = "bold") -> Optional[str]:
    """Find a CJK-capable font on the current system.

    Args:
        weight: "bold" for titles (W6-W8), "regular" for body/badges (W3-W4).

    Returns:
        Absolute path to a TTC/TTF/OTF font file, or None if not found.
    """
    cache_key = weight
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]

    candidates: list[str] = []
    system = platform.system()

    if system == "Darwin":
        if weight == "bold":
            candidates = [
                "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
                "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc",
                "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
            ]
        else:
            candidates = [
                "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc",
                "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            ]
    elif system == "Linux":
        # VPS with fonts-noto-cjk
        if weight == "bold":
            candidates = [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/google-noto-cjk/NotoSansCJKjp-Bold.otf",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            ]
        else:
            candidates = [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/google-noto-cjk/NotoSansCJKjp-Regular.otf",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            ]

    for path in candidates:
        if Path(path).exists():
            _FONT_CACHE[cache_key] = path
            return path

    # Last-resort: scan common directories
    search_dirs = [
        Path("/usr/share/fonts"),
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
    ]
    keywords_bold = ["CJK", "Gothic", "ゴシック"]
    keywords_reg = keywords_bold  # same family, different weight handled by filename

    for d in search_dirs:
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.suffix.lower() not in (".ttf", ".ttc", ".otf"):
                continue
            name = f.name
            if any(kw in name for kw in keywords_bold):
                _FONT_CACHE[cache_key] = str(f)
                return str(f)

    _FONT_CACHE[cache_key] = None
    return None


def _load_font(size: int, weight: str = "bold") -> ImageFont.FreeTypeFont:
    """Load a font at the given size, falling back to default if necessary."""
    path = _find_font(weight)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            logger.warning("Failed to load font %s at size %d, using default", path, size)
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _draw_gradient(img: Image.Image, start: tuple, end: tuple) -> None:
    """Draw a diagonal gradient across the entire image."""
    pixels = img.load()
    w, h = img.size
    # Diagonal: blend based on normalised (x + y) / (w + h)
    max_dist = w + h
    for y in range(h):
        for x in range(w):
            t = (x + y) / max_dist
            r = int(start[0] + (end[0] - start[0]) * t)
            g = int(start[1] + (end[1] - start[1]) * t)
            b = int(start[2] + (end[2] - start[2]) * t)
            pixels[x, y] = (r, g, b)


def _draw_gradient_fast(img: Image.Image, start: tuple, end: tuple) -> None:
    """Draw a diagonal gradient using horizontal-line averaging for speed."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    steps = h
    for y in range(steps):
        # Average blend factor for this row
        t_left = y / (w + h)
        t_right = (w + y) / (w + h)
        t = (t_left + t_right) / 2.0
        r = int(start[0] + (end[0] - start[0]) * t)
        g = int(start[1] + (end[1] - start[1]) * t)
        b = int(start[2] + (end[2] - start[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


def _draw_geometric_pattern(draw: ImageDraw.Draw, w: int, h: int, accent: tuple) -> None:
    """Draw a subtle geometric pattern overlay (thin diagonal lines + dots)."""
    # Subtle opacity via faded colour
    line_color = (*accent, 18)  # very faint

    # Diagonal lines (top-left to bottom-right)
    spacing = 60
    for offset in range(-h, w + h, spacing):
        draw.line(
            [(offset, 0), (offset + h, h)],
            fill=line_color,
            width=1,
        )

    # Small dots at intersections
    dot_color = (*accent, 25)
    dot_r = 2
    for gx in range(0, w + spacing, spacing):
        for gy in range(0, h + spacing, spacing):
            draw.ellipse(
                [gx - dot_r, gy - dot_r, gx + dot_r, gy + dot_r],
                fill=dot_color,
            )


def _draw_badge(
    draw: ImageDraw.Draw,
    text: str,
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    bg_color: tuple,
    text_color: tuple,
    padding_h: int = 16,
    padding_v: int = 8,
) -> tuple[int, int]:
    """Draw a rounded-rectangle badge. Returns (width, height) of the badge."""
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    bw = tw + padding_h * 2
    bh = th + padding_v * 2

    draw.rounded_rectangle(
        [x, y, x + bw, y + bh],
        radius=6,
        fill=bg_color,
    )
    # Centre text inside badge
    tx = x + padding_h
    ty = y + padding_v - bbox[1]  # offset for font ascent
    draw.text((tx, ty), text, fill=text_color, font=font)

    return bw, bh


def _wrap_title(title: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int = 3) -> list[str]:
    """Wrap a title into lines that fit within max_width pixels.

    For CJK text, wraps character-by-character.
    Truncates with '...' if exceeding max_lines.
    """
    lines: list[str] = []
    current = ""

    for ch in title:
        test = current + ch
        bbox = font.getbbox(test)
        tw = bbox[2] - bbox[0]
        if tw > max_width and current:
            lines.append(current)
            current = ch
            if len(lines) >= max_lines:
                break
        else:
            current = test

    if current and len(lines) < max_lines:
        lines.append(current)

    # If we exceeded max_lines, truncate the last line
    if len(lines) >= max_lines:
        last = lines[max_lines - 1]
        # Ensure the last line fits with "..."
        while last:
            test = last + "..."
            bbox = font.getbbox(test)
            tw = bbox[2] - bbox[0]
            if tw <= max_width:
                lines[max_lines - 1] = test
                break
            last = last[:-1]
        lines = lines[:max_lines]

    return lines


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
    """Generate a branded article thumbnail image.

    Args:
        title: Article title (Japanese text).
        country: Country key (uae, saudi, brunei, japan).
        genre: Genre key for the badge label.
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

    # --- Create base image with gradient ---
    img = Image.new("RGB", (WIDTH, HEIGHT))
    _draw_gradient_fast(img, theme["gradient_start"], theme["gradient_end"])

    # --- Overlay for geometric pattern (RGBA for transparency) ---
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    _draw_geometric_pattern(overlay_draw, WIDTH, HEIGHT, theme["accent"])
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)

    # --- Load fonts ---
    font_title = _load_font(52, "bold")
    font_badge = _load_font(22, "regular")
    font_brand = _load_font(16, "regular")

    # --- Country badge (top-left) ---
    margin = 40
    _draw_badge(
        draw,
        theme["label"],
        x=margin,
        y=margin,
        font=font_badge,
        bg_color=theme["badge_bg"],
        text_color=theme["badge_text"],
    )

    # --- Genre badge (top-right) ---
    genre_label = GENRE_LABELS.get(genre, "ビジネス")
    genre_bbox = font_badge.getbbox(genre_label)
    genre_tw = genre_bbox[2] - genre_bbox[0]
    genre_badge_w = genre_tw + 32  # padding_h * 2
    _draw_badge(
        draw,
        genre_label,
        x=WIDTH - margin - genre_badge_w,
        y=margin,
        font=font_badge,
        bg_color=(*theme["accent"][:3], 200) if len(theme["accent"]) == 3 else theme["accent"],
        text_color=theme["badge_text"],
        padding_h=16,
        padding_v=8,
    )

    # --- Article title (centred vertically) ---
    max_title_width = WIDTH - margin * 2 - 40  # some extra margin
    lines = _wrap_title(title, font_title, max_title_width, max_lines=3)

    # Calculate total text block height
    line_heights: list[int] = []
    for line in lines:
        bbox = font_title.getbbox(line)
        line_heights.append(bbox[3] - bbox[1])

    line_spacing = 16
    total_text_h = sum(line_heights) + line_spacing * (len(lines) - 1) if lines else 0

    # Vertical centre (shifted down slightly to account for badges)
    top_zone = margin + 50  # below badges
    bottom_zone = HEIGHT - 80  # above bottom bar
    available_h = bottom_zone - top_zone
    start_y = top_zone + (available_h - total_text_h) // 2

    # Draw each line with shadow
    shadow_offset = 2
    shadow_color = (0, 0, 0, 160)
    y_cursor = start_y
    for i, line in enumerate(lines):
        bbox = font_title.getbbox(line)
        tw = bbox[2] - bbox[0]
        tx = (WIDTH - tw) // 2

        # Drop shadow
        draw.text(
            (tx + shadow_offset, y_cursor + shadow_offset),
            line,
            fill=(0, 0, 0),
            font=font_title,
        )
        # Main text
        draw.text(
            (tx, y_cursor),
            line,
            fill=(255, 255, 255),
            font=font_title,
        )
        y_cursor += line_heights[i] + line_spacing

    # --- Bottom accent line ---
    accent_line_y = HEIGHT - 8
    draw.rectangle(
        [0, accent_line_y, WIDTH, HEIGHT],
        fill=theme["accent"],
    )

    # --- Branding text (bottom-right, above accent line) ---
    brand_text = "Connect-Sekai"
    brand_bbox = font_brand.getbbox(brand_text)
    brand_tw = brand_bbox[2] - brand_bbox[0]
    draw.text(
        (WIDTH - margin - brand_tw, HEIGHT - 36),
        brand_text,
        fill=(255, 255, 255, 180) if len(theme["accent"]) >= 3 else (200, 200, 200),
        font=font_brand,
    )

    # --- Thin separator line above branding ---
    sep_y = HEIGHT - 50
    draw.line(
        [(margin, sep_y), (WIDTH - margin, sep_y)],
        fill=(*theme["accent"][:3], 60),
        width=1,
    )

    # --- Save ---
    img.save(str(output_path), "JPEG", quality=85, optimize=True)
    logger.info("Generated thumbnail: %s", output_path)

    return output_path


# ---------------------------------------------------------------------------
# Convenience: classify genre from article data
# ---------------------------------------------------------------------------

def classify_genre(title: str, body: str, genres_config: dict[str, Any]) -> str:
    """Classify an article into a genre based on keyword matching.

    Mirrors the logic in SiteGenerator._classify_genre.
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
