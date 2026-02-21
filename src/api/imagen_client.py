"""Nano Banana Pro (Gemini 3 Pro Image) API wrapper for Connect-Sekai."""

from __future__ import annotations

import io
import os
import logging
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
import google.generativeai as genai
from PIL import Image

load_dotenv()
logger = logging.getLogger(__name__)

ImageSize = Literal["1080x1080", "1080x1350", "1080x1920"]

SIZE_MAP: dict[str, tuple[int, int]] = {
    "1080x1080": (1080, 1080),   # Instagram square
    "1080x1350": (1080, 1350),   # Instagram portrait
    "1080x1920": (1080, 1920),   # TikTok / Stories
}


class ImagenClient:
    """Generates images using Nano Banana Pro (Gemini 3 Pro Image)."""

    def __init__(self, model_name: str = "gemini-3-pro-image-preview") -> None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY is not set in .env")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)

    def generate_image(self, prompt: str, size: ImageSize = "1080x1080") -> Image.Image:
        """Generate an image from a text prompt.

        Args:
            prompt: Text description of the desired image.
            size: Target output size (the image is resized after generation).

        Returns:
            A PIL Image object.

        Raises:
            RuntimeError: If image generation fails.
        """
        width, height = SIZE_MAP[size]
        full_prompt = (
            f"{prompt}\n\n"
            f"Image specifications: high quality, photorealistic, "
            f"aspect ratio suitable for {width}x{height} pixels."
        )

        try:
            response = self.model.generate_content(
                full_prompt,
                generation_config=genai.GenerationConfig(
                    response_modalities=["image", "text"],
                ),
            )
        except Exception as e:
            raise RuntimeError(f"Image generation API call failed: {e}") from e

        # Extract image data from the response parts
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                image = Image.open(io.BytesIO(part.inline_data.data))
                image = image.resize((width, height), Image.LANCZOS)
                return image

        raise RuntimeError(
            "No image data returned from API. "
            "The model may have returned text only."
        )

    def save_image(
        self,
        image: Image.Image,
        path: str | Path,
        fmt: str = "PNG",
    ) -> Path:
        """Save a PIL Image to disk, creating parent directories as needed.

        Args:
            image: The PIL Image to save.
            path: Destination file path.
            fmt: Image format (PNG, JPEG, etc.).

        Returns:
            The resolved Path where the file was saved.
        """
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        image.save(dest, format=fmt)
        logger.info("Image saved: %s", dest)
        return dest

    def generate_and_save(
        self,
        prompt: str,
        path: str | Path,
        size: ImageSize = "1080x1080",
        fmt: str = "PNG",
    ) -> Path:
        """Generate an image and save it to disk in one step.

        Args:
            prompt: Text description of the desired image.
            path: Destination file path.
            size: Target output size.
            fmt: Image format.

        Returns:
            The resolved Path where the file was saved.
        """
        image = self.generate_image(prompt, size=size)
        return self.save_image(image, path, fmt=fmt)
