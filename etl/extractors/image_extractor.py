# etl/extractors/image_extractor.py
"""Image extraction, captioning, and embedding for multi-modal RAG."""

import logging
import os
import re
from dataclasses import dataclass, field

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

logger = logging.getLogger(__name__)

IMAGE_EXTRACTION_ENABLED = True
IMAGE_MODEL = "clip-ViT-B-32"


@dataclass
class ImageInfo:
    src: str
    alt: str = ""
    caption: str = ""
    embedding: list[float] = field(default_factory=list)


def extract_images_from_html(html: str) -> list[ImageInfo]:
    """Extract image tags from HTML, returning ImageInfo objects.

    Skips data: URIs and images without a src attribute.
    """
    if not html:
        return []

    results = []

    if BS4_AVAILABLE:
        try:
            soup = BeautifulSoup(html, "html.parser")  # noqa: F821
            for img in soup.find_all("img"):
                src = str(img.get("src", "") or "")
                if not src or src.startswith("data:"):
                    continue
                alt = str(img.get("alt", "") or "")
                results.append(ImageInfo(src=src, alt=alt))
            return results
        except Exception:
            pass

    pattern = re.compile(
        r'<img[^>]*?\s+(?:src\s*=\s*"([^"]*)"|src\s*=\s*\'([^\']*)\')',
        re.IGNORECASE,
    )
    alt_pattern = re.compile(
        r'<img[^>]*?\s+alt\s*=\s*"([^"]*)"',
        re.IGNORECASE,
    )

    for match in pattern.finditer(html):
        src = match.group(1) or match.group(2) or ""
        if not src or src.startswith("data:"):
            continue
        alt = ""
        alt_pos = html.find(f'src="{src}"')
        if alt_pos < 0:
            alt_pos = html.find(f"src='{src}'")
        if alt_pos >= 0:
            tag_section = html[max(0, alt_pos - 200):alt_pos + len(src) + 50]
            am = alt_pattern.search(tag_section)
            if am:
                alt = am.group(1)
        results.append(ImageInfo(src=src, alt=alt))

    return results


def caption_image(image_path: str, alt_text: str = "") -> str:
    """Generate a textual caption for an image.

    Air-gap compatible: uses filename analysis, alt text, and heuristics.
    For real CLIP/BLIP captioning, override this with a vision model.

    :param image_path: path or URL of the image
    :param alt_text: optional alt attribute text from HTML
    :return: human-readable caption string
    """
    if alt_text and len(alt_text.strip()) > 1:
        return f"[Image: {alt_text.strip()}]"

    if image_path:
        filename = image_path.rsplit("/", 1)[-1] if "/" in image_path else image_path
        if filename:
            name_part = filename.rsplit(".", 1)[0] if "." in filename else filename
            readable = re.sub(r"[_-]+", " ", name_part).strip()
            if readable:
                return f"[Image: {readable}]"

    return "[Image: untitled]"


def embed_image(image_path: str) -> list[float]:
    """Compute dense embedding for an image.

    Placeholder for CLIP or similar vision model.
    Air-gap compatible: returns empty embedding by default.
    Override for actual CLIP/SigLIP integration.

    :param image_path: path to the image file
    :return: list of float values representing the embedding
    """
    if not IMAGE_EXTRACTION_ENABLED:
        return []

    if not image_path or not os.path.exists(image_path):
        logger.debug("Image not found for embedding: %s", image_path)
        return []

    logger.info("Placeholder embed_image called for %s — integrate CLIP model here", image_path)
    return []
