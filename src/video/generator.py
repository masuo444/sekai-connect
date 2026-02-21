"""TikTok 動画自動生成エンジン。

記事タイトル・本文から 30-45 秒の縦型動画 (1080x1920) を生成する。
moviepy + PIL/Pillow ベースのフレーム描画方式を採用し、
moviepy TextClip のフォント問題を回避する。

動画構成:
  Scene 1 (3s) : Connect-Sekai ロゴ + 国旗 + ジャンルバッジ
  Scene 2 (5s) : 記事タイトル (フェードイン)
  Scene 3-5 (7s each) : 記事の要点 3 つ (フェードイン)
  Scene 6 (3s) : CTA + ハッシュタグ
  合計: 3 + 5 + 7*3 + 3 = 32 秒

依存: moviepy, Pillow, numpy
外部依存: ffmpeg (moviepy のバックエンド)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 24
# moviepy の write_videofile で使う codec / bitrate
VIDEO_CODEC = "libx264"
VIDEO_BITRATE = "4000k"  # TikTok 上限 50MB に余裕を持たせる

# シーン秒数
SCENE_LOGO_DURATION = 3.0
SCENE_TITLE_DURATION = 5.0
SCENE_POINT_DURATION = 7.0
SCENE_CTA_DURATION = 3.0

# 国別アクセントカラー
COUNTRY_ACCENT: dict[str, str] = {
    "uae": "#D4AF37",
    "saudi": "#006C35",
    "brunei": "#F7E017",
    "japan": "#BC002D",
}

# 国別フラグ表示テキスト (Unicode flag sequences)
COUNTRY_FLAG: dict[str, str] = {
    "uae": "\U0001F1E6\U0001F1EA",      # AE
    "saudi": "\U0001F1F8\U0001F1E6",    # SA
    "brunei": "\U0001F1E7\U0001F1F3",   # BN
    "japan": "\U0001F1EF\U0001F1F5",    # JP
}

COUNTRY_NAME_JA: dict[str, str] = {
    "uae": "UAE",
    "saudi": "Saudi Arabia",
    "brunei": "Brunei",
    "japan": "Japan",
}

# 背景グラデーション (上 → 下)
BG_COLOR_TOP = (10, 15, 40)       # 濃紺
BG_COLOR_BOTTOM = (20, 35, 80)    # やや明るい紺

# テキスト色
TEXT_COLOR_WHITE = (255, 255, 255)
TEXT_COLOR_SHADOW = (0, 0, 0, 100)
TEXT_COLOR_SUBTLE = (180, 190, 210)

# ---------------------------------------------------------------------------
# フォント検出
# ---------------------------------------------------------------------------

_FONT_CACHE: dict[str, Optional[ImageFont.FreeTypeFont]] = {}

# 日本語フォント候補 (macOS → Linux → Windows → フォールバック)
_JP_FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴ ProN W6.otf",
    "/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    # macOS English names
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W5.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc",
    # Noto Sans JP (Linux / manual install)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJKjp-Bold.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJKjp-Regular.otf",
    # Windows
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
]

# 英語フォント候補 (太字)
_EN_FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFPro.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    # Windows
    "C:/Windows/Fonts/arialbd.ttf",
]


def _find_font(candidates: list[str]) -> Optional[str]:
    """候補リストから最初に見つかったフォントパスを返す。"""
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """日本語対応フォントを取得する。見つからなければデフォルトにフォールバック。"""
    cache_key = f"jp_{size}_{bold}"
    if cache_key in _FONT_CACHE and _FONT_CACHE[cache_key] is not None:
        return _FONT_CACHE[cache_key]  # type: ignore[return-value]

    font_path = _find_font(_JP_FONT_CANDIDATES)
    if font_path is None:
        # 日本語フォントが見つからない場合は英語フォントで代替
        font_path = _find_font(_EN_FONT_CANDIDATES)

    if font_path is not None:
        try:
            font = ImageFont.truetype(font_path, size)
            _FONT_CACHE[cache_key] = font
            return font
        except Exception as e:
            logger.warning("フォント読み込み失敗 (%s): %s", font_path, e)

    # 最終フォールバック: PIL デフォルト
    logger.warning("日本語フォントが見つかりません。デフォルトフォントを使用します。")
    font = ImageFont.load_default()
    _FONT_CACHE[cache_key] = font  # type: ignore[assignment]
    return font  # type: ignore[return-value]


def _get_en_font(size: int) -> ImageFont.FreeTypeFont:
    """英語用フォントを取得する。"""
    cache_key = f"en_{size}"
    if cache_key in _FONT_CACHE and _FONT_CACHE[cache_key] is not None:
        return _FONT_CACHE[cache_key]  # type: ignore[return-value]

    font_path = _find_font(_EN_FONT_CANDIDATES)
    if font_path is None:
        font_path = _find_font(_JP_FONT_CANDIDATES)

    if font_path is not None:
        try:
            font = ImageFont.truetype(font_path, size)
            _FONT_CACHE[cache_key] = font
            return font
        except Exception:
            pass

    font = ImageFont.load_default()
    _FONT_CACHE[cache_key] = font  # type: ignore[assignment]
    return font  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 描画ユーティリティ
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """#RRGGBB → (R, G, B)"""
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def _create_gradient_bg() -> Image.Image:
    """縦型グラデーション背景を生成する。"""
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT))
    draw = ImageDraw.Draw(img)

    for y in range(VIDEO_HEIGHT):
        ratio = y / VIDEO_HEIGHT
        r = int(BG_COLOR_TOP[0] + (BG_COLOR_BOTTOM[0] - BG_COLOR_TOP[0]) * ratio)
        g = int(BG_COLOR_TOP[1] + (BG_COLOR_BOTTOM[1] - BG_COLOR_TOP[1]) * ratio)
        b = int(BG_COLOR_TOP[2] + (BG_COLOR_BOTTOM[2] - BG_COLOR_TOP[2]) * ratio)
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(r, g, b))

    return img


def _draw_text_shadow(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, ...] = TEXT_COLOR_WHITE,
    shadow_offset: int = 2,
) -> None:
    """テキストに影を付けて描画する。"""
    x, y = position
    # 影
    draw.text(
        (x + shadow_offset, y + shadow_offset),
        text,
        font=font,
        fill=(0, 0, 0, 120),
    )
    # 本体
    draw.text((x, y), text, font=font, fill=fill)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """テキストを指定幅に収まるように改行する。日本語対応。"""
    lines: list[str] = []

    # まず明示的な改行で分割
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        # 1文字ずつ追加して幅を測る
        current_line = ""
        for char in paragraph:
            test_line = current_line + char
            bbox = font.getbbox(test_line)
            width = bbox[2] - bbox[0]
            if width > max_width and current_line:
                lines.append(current_line)
                current_line = char
            else:
                current_line = test_line
        if current_line:
            lines.append(current_line)

    return lines


def _draw_accent_line(
    draw: ImageDraw.ImageDraw,
    y: int,
    accent_color: tuple[int, int, int],
    width: int = 120,
    thickness: int = 4,
) -> None:
    """アクセントカラーの水平ラインを描画する (中央揃え)。"""
    x_start = (VIDEO_WIDTH - width) // 2
    x_end = x_start + width
    draw.rectangle(
        [(x_start, y), (x_end, y + thickness)],
        fill=accent_color,
    )


def _draw_genre_badge(
    draw: ImageDraw.ImageDraw,
    text: str,
    position: tuple[int, int],
    accent_color: tuple[int, int, int],
    font: ImageFont.FreeTypeFont,
) -> None:
    """ジャンルバッジ (角丸矩形 + テキスト) を描画する。"""
    bbox = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    padding_x = 24
    padding_y = 10
    x, y = position
    # 角丸矩形
    draw.rounded_rectangle(
        [(x, y), (x + text_w + padding_x * 2, y + text_h + padding_y * 2)],
        radius=12,
        fill=accent_color,
    )
    # テキスト
    draw.text(
        (x + padding_x, y + padding_y),
        text,
        font=font,
        fill=TEXT_COLOR_WHITE,
    )


# ---------------------------------------------------------------------------
# シーンフレーム生成
# ---------------------------------------------------------------------------

def _make_logo_frame(
    country: str,
    genre: str,
    accent_color: tuple[int, int, int],
) -> np.ndarray:
    """Scene 1: Connect-Sekai ロゴ + 国旗 + ジャンルバッジのフレームを生成。"""
    img = _create_gradient_bg()
    draw = ImageDraw.Draw(img)

    # ── ロゴテキスト "CONNECT-SEKAI" ──
    logo_font = _get_en_font(72)
    logo_text = "CONNECT-SEKAI"
    logo_bbox = logo_font.getbbox(logo_text)
    logo_w = logo_bbox[2] - logo_bbox[0]
    logo_x = (VIDEO_WIDTH - logo_w) // 2
    logo_y = 700

    _draw_text_shadow(draw, (logo_x, logo_y), logo_text, logo_font)

    # ── アクセントライン ──
    _draw_accent_line(draw, logo_y + 100, accent_color, width=200, thickness=5)

    # ── 国名 ──
    country_font = _get_font(48)
    country_name = COUNTRY_NAME_JA.get(country, country.upper())
    flag = COUNTRY_FLAG.get(country, "")
    country_display = f"{flag}  {country_name}" if flag else country_name
    country_bbox = country_font.getbbox(country_display)
    country_w = country_bbox[2] - country_bbox[0]
    country_x = (VIDEO_WIDTH - country_w) // 2
    country_y = logo_y + 140

    _draw_text_shadow(draw, (country_x, country_y), country_display, country_font)

    # ── ジャンルバッジ ──
    if genre:
        badge_font = _get_font(32)
        badge_bbox = badge_font.getbbox(genre)
        badge_w = badge_bbox[2] - badge_bbox[0] + 48
        badge_x = (VIDEO_WIDTH - badge_w) // 2
        badge_y = country_y + 100
        _draw_genre_badge(draw, genre, (badge_x, badge_y), accent_color, badge_font)

    # ── サブタグライン ──
    sub_font = _get_font(28)
    sub_text = "Business Intelligence Hub"
    sub_bbox = sub_font.getbbox(sub_text)
    sub_w = sub_bbox[2] - sub_bbox[0]
    sub_x = (VIDEO_WIDTH - sub_w) // 2
    sub_y = 1100
    _draw_text_shadow(
        draw, (sub_x, sub_y), sub_text, sub_font,
        fill=TEXT_COLOR_SUBTLE,
    )

    return np.array(img)


def _make_title_frame(
    title: str,
    country: str,
    accent_color: tuple[int, int, int],
) -> np.ndarray:
    """Scene 2: 記事タイトルのフレームを生成。"""
    img = _create_gradient_bg()
    draw = ImageDraw.Draw(img)

    # ── 上部アクセントライン ──
    _draw_accent_line(draw, 600, accent_color, width=160, thickness=4)

    # ── タイトルテキスト ──
    title_font = _get_font(56)
    max_width = VIDEO_WIDTH - 140  # 左右 70px マージン
    lines = _wrap_text(title, title_font, max_width)

    # 中央縦位置を計算
    line_height = 80
    total_height = len(lines) * line_height
    start_y = 660

    for i, line in enumerate(lines):
        bbox = title_font.getbbox(line)
        line_w = bbox[2] - bbox[0]
        x = (VIDEO_WIDTH - line_w) // 2
        y = start_y + i * line_height
        _draw_text_shadow(draw, (x, y), line, title_font)

    # ── 下部にソース表記 ──
    src_font = _get_font(26)
    src_text = "connect-sekai.com"
    src_bbox = src_font.getbbox(src_text)
    src_w = src_bbox[2] - src_bbox[0]
    src_x = (VIDEO_WIDTH - src_w) // 2
    src_y = start_y + total_height + 60
    _draw_text_shadow(
        draw, (src_x, src_y), src_text, src_font,
        fill=TEXT_COLOR_SUBTLE,
    )

    return np.array(img)


def _make_point_frame(
    point_number: int,
    point_text: str,
    country: str,
    accent_color: tuple[int, int, int],
) -> np.ndarray:
    """Scene 3-5: 要点フレームを生成。"""
    img = _create_gradient_bg()
    draw = ImageDraw.Draw(img)

    # ── ポイント番号 ──
    num_font = _get_en_font(120)
    num_text = str(point_number)
    num_bbox = num_font.getbbox(num_text)
    num_w = num_bbox[2] - num_bbox[0]
    num_x = (VIDEO_WIDTH - num_w) // 2
    num_y = 550

    # 番号を薄いアクセントカラーで表示
    accent_faded = tuple(min(255, c + 60) for c in accent_color)
    _draw_text_shadow(
        draw, (num_x, num_y), num_text, num_font,
        fill=accent_faded,  # type: ignore[arg-type]
    )

    # ── アクセントライン ──
    _draw_accent_line(draw, num_y + 160, accent_color, width=80, thickness=3)

    # ── ポイントテキスト ──
    point_font = _get_font(44)
    max_width = VIDEO_WIDTH - 160
    lines = _wrap_text(point_text, point_font, max_width)

    line_height = 68
    total_height = len(lines) * line_height
    start_y = num_y + 200

    for i, line in enumerate(lines):
        bbox = point_font.getbbox(line)
        line_w = bbox[2] - bbox[0]
        x = (VIDEO_WIDTH - line_w) // 2
        y = start_y + i * line_height
        _draw_text_shadow(draw, (x, y), line, point_font)

    return np.array(img)


def _make_cta_frame(
    hashtags: str,
    accent_color: tuple[int, int, int],
) -> np.ndarray:
    """Scene 6: CTA + ハッシュタグのフレームを生成。"""
    img = _create_gradient_bg()
    draw = ImageDraw.Draw(img)

    # ── ロゴ (小さめ) ──
    logo_font = _get_en_font(52)
    logo_text = "CONNECT-SEKAI"
    logo_bbox = logo_font.getbbox(logo_text)
    logo_w = logo_bbox[2] - logo_bbox[0]
    logo_x = (VIDEO_WIDTH - logo_w) // 2
    logo_y = 650
    _draw_text_shadow(draw, (logo_x, logo_y), logo_text, logo_font)

    # ── アクセントライン ──
    _draw_accent_line(draw, logo_y + 80, accent_color, width=160, thickness=4)

    # ── CTA テキスト ──
    cta_font = _get_font(40)
    cta_text = "connect-sekai.com"
    cta_bbox = cta_font.getbbox(cta_text)
    cta_w = cta_bbox[2] - cta_bbox[0]
    cta_x = (VIDEO_WIDTH - cta_w) // 2
    cta_y = logo_y + 120
    _draw_text_shadow(draw, (cta_x, cta_y), cta_text, cta_font)

    # ── ハッシュタグ ──
    if hashtags:
        tag_font = _get_font(30)
        max_width = VIDEO_WIDTH - 120
        tag_lines = _wrap_text(hashtags, tag_font, max_width)
        line_height = 48
        tag_start_y = cta_y + 100

        for i, line in enumerate(tag_lines):
            bbox = tag_font.getbbox(line)
            line_w = bbox[2] - bbox[0]
            x = (VIDEO_WIDTH - line_w) // 2
            y = tag_start_y + i * line_height
            _draw_text_shadow(
                draw, (x, y), line, tag_font,
                fill=TEXT_COLOR_SUBTLE,
            )

    return np.array(img)


# ---------------------------------------------------------------------------
# フェードイン合成
# ---------------------------------------------------------------------------

def _apply_fade_in(
    clip: Any,
    duration: float = 0.8,
) -> Any:
    """クリップにフェードイン効果を適用する。"""
    from moviepy import vfx
    return clip.with_effects([vfx.FadeIn(duration)])


# ---------------------------------------------------------------------------
# メインジェネレータクラス
# ---------------------------------------------------------------------------

class TikTokVideoGenerator:
    """記事データからTikTok用縦型動画を生成するクラス。

    使い方::

        gen = TikTokVideoGenerator()
        output_path = gen.generate(
            title="ドバイの不動産市場が急成長",
            body="...",
            key_points=["要点1", "要点2", "要点3"],
            country="uae",
            hashtags="#ドバイ #UAE #不動産投資",
            genre="ビジネス",
            output_path=Path("data/videos/uae/2026-02-21_article.mp4"),
        )
    """

    def __init__(self, output_dir: Optional[Path] = None) -> None:
        self._root = Path(__file__).resolve().parent.parent.parent
        self.output_dir = output_dir or (self._root / "data" / "videos")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        title: str,
        body: str,
        key_points: list[str],
        country: str,
        hashtags: str = "",
        genre: str = "",
        output_path: Optional[Path] = None,
    ) -> Path:
        """記事データから TikTok 動画を生成して保存する。

        Args:
            title: 記事タイトル。
            body: 記事本文 (参考用。要点はkey_pointsで渡す)。
            key_points: 記事の要点 3 つ。
            country: 国キー (uae, saudi, brunei, japan)。
            hashtags: ハッシュタグ文字列。
            genre: ジャンル名 (表示用)。
            output_path: 出力先パス。None の場合は自動生成。

        Returns:
            出力された MP4 ファイルのパス。
        """
        from moviepy import ImageClip, concatenate_videoclips

        accent_hex = COUNTRY_ACCENT.get(country, "#D4AF37")
        accent_rgb = _hex_to_rgb(accent_hex)

        # 要点が 3 つに満たない場合は補填
        while len(key_points) < 3:
            key_points.append("")
        key_points = key_points[:3]

        logger.info("動画生成開始: %s (%s)", title[:40], country)

        # ── 各シーンのフレームを生成 ──
        logo_frame = _make_logo_frame(country, genre, accent_rgb)
        title_frame = _make_title_frame(title, country, accent_rgb)
        point_frames = [
            _make_point_frame(i + 1, kp, country, accent_rgb)
            for i, kp in enumerate(key_points)
            if kp  # 空の要点はスキップ
        ]
        cta_frame = _make_cta_frame(hashtags, accent_rgb)

        # ── moviepy クリップを構築 ──
        clips = []

        # Scene 1: ロゴ
        clip_logo = ImageClip(logo_frame, duration=SCENE_LOGO_DURATION)
        clip_logo = _apply_fade_in(clip_logo, 0.6)
        clips.append(clip_logo)

        # Scene 2: タイトル
        clip_title = ImageClip(title_frame, duration=SCENE_TITLE_DURATION)
        clip_title = _apply_fade_in(clip_title, 0.8)
        clips.append(clip_title)

        # Scene 3-5: 要点
        for pf in point_frames:
            clip_point = ImageClip(pf, duration=SCENE_POINT_DURATION)
            clip_point = _apply_fade_in(clip_point, 0.6)
            clips.append(clip_point)

        # Scene 6: CTA
        clip_cta = ImageClip(cta_frame, duration=SCENE_CTA_DURATION)
        clip_cta = _apply_fade_in(clip_cta, 0.5)
        clips.append(clip_cta)

        # ── 結合 ──
        final = concatenate_videoclips(clips, method="compose")

        # ── 出力パス決定 ──
        if output_path is None:
            from datetime import datetime, timezone
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            slug = _slugify(title)
            country_dir = self.output_dir / country
            country_dir.mkdir(parents=True, exist_ok=True)
            output_path = country_dir / f"{date_str}_{slug}.mp4"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # ── 動画書き出し ──
        logger.info("動画書き出し中: %s", output_path)
        final.write_videofile(
            str(output_path),
            fps=FPS,
            codec=VIDEO_CODEC,
            bitrate=VIDEO_BITRATE,
            audio=False,
            logger=None,  # moviepy のプログレスバーを抑制
        )

        file_size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(
            "動画生成完了: %s (%.1f MB, %.0f 秒)",
            output_path.name,
            file_size_mb,
            final.duration,
        )

        # TikTok 上限チェック
        if file_size_mb > 50:
            logger.warning(
                "動画サイズが TikTok 上限 (50MB) を超えています: %.1f MB",
                file_size_mb,
            )

        return output_path


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _slugify(text: str, max_len: int = 50) -> str:
    """テキストを URL-safe なスラッグに変換する。"""
    # ASCII 文字のみ残す (日本語は除去)
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    if not slug:
        slug = "article"
    return slug[:max_len]
