# etl/extractors/image_extractor.py
"""Image extraction, captioning, embedding, and OCR for multi-modal RAG.

FR-09: OCR pipeline with pytesseract (primary) + easyocr (fallback)
FR-10: Image embedding with CLIP + captioning with BLIP
"""

import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

IMAGE_EXTRACTION_ENABLED = os.getenv("IMAGE_EXTRACTION_ENABLED", "false").lower() == "true"
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "clip-ViT-B-32")
CLIP_MODEL_NAME = os.getenv("CLIP_MODEL_NAME", "openai/clip-vit-base-patch32")
BLIP_MODEL_NAME = os.getenv("BLIP_MODEL_NAME", "Salesforce/blip-image-captioning-base")

# FR-09: OCR configuration
OCR_ENABLED = os.getenv("OCR_ENABLED", "true").lower() == "true"
OCR_LANGUAGES = os.getenv("OCR_LANGUAGES", "rus+eng")
OCR_CONFIDENCE_THRESHOLD = int(os.getenv("OCR_CONFIDENCE_THRESHOLD", "60"))
OCR_PRIMARY_ENGINE = os.getenv("OCR_PRIMARY_ENGINE", "tesseract")  # "tesseract" or "easyocr"

SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp", ".pdf"}

# ── Lazy-loaded model caches ──────────────────────────────────────────────────

_clip_model = None
_clip_processor = None
_blip_model = None
_blip_processor = None
_easyocr_reader = None


def _ensure_pytesseract():
    try:
        import pytesseract as pt
        return pt
    except ImportError:
        return None


def _ensure_pil():
    try:
        from PIL import Image as PILImage

        return PILImage
    except ImportError:
        return None


def _ensure_easyocr(langs: list[str] | None = None):
    global _easyocr_reader
    if _easyocr_reader is not None:
        return _easyocr_reader
    try:
        import easyocr
        _easyocr_reader = easyocr.Reader(langs or ["ru", "en"], gpu=False)
        return _easyocr_reader
    except ImportError:
        return None


def _ensure_clip():
    global _clip_model, _clip_processor
    if _clip_model is not None:
        return _clip_model, _clip_processor
    try:
        import torch
        from transformers import CLIPModel, CLIPProcessor

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = CLIPModel.from_pretrained(CLIP_MODEL_NAME).to(device)
        processor = CLIPProcessor.from_pretrained(CLIP_MODEL_NAME)
        _clip_model = model
        _clip_processor = processor
        logger.info("CLIP model loaded: %s on %s", CLIP_MODEL_NAME, device)
        return model, processor
    except ImportError:
        logger.warning("transformers/torch not installed — CLIP unavailable")
        return None, None
    except Exception as e:
        logger.warning("Failed to load CLIP: %s", e)
        return None, None


def _ensure_blip():
    global _blip_model, _blip_processor
    if _blip_model is not None:
        return _blip_model, _blip_processor
    try:
        import torch
        from transformers import BlipForConditionalGeneration, BlipProcessor

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = BlipForConditionalGeneration.from_pretrained(BLIP_MODEL_NAME).to(device)
        processor = BlipProcessor.from_pretrained(BLIP_MODEL_NAME)
        _blip_model = model
        _blip_processor = processor
        logger.info("BLIP model loaded: %s on %s", BLIP_MODEL_NAME, device)
        return model, processor
    except ImportError:
        logger.warning("transformers/torch not installed — BLIP unavailable")
        return None, None
    except Exception as e:
        logger.warning("Failed to load BLIP: %s", e)
        return None, None


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class ImageInfo:
    src: str
    alt: str = ""
    caption: str = ""
    embedding: list[float] = field(default_factory=list)


@dataclass
class OCRResult:
    text: str
    confidence: float
    language: str = ""
    page_number: int = 0
    blocks: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_above_threshold(self) -> bool:
        return self.confidence >= OCR_CONFIDENCE_THRESHOLD


@dataclass
class ExtractedImage:
    path: str
    page_number: int = 0
    width: int = 0
    height: int = 0
    format: str = ""
    ocr_text: str = ""
    ocr_confidence: float = 0.0
    caption: str = ""
    embedding: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── HTML image extraction ─────────────────────────────────────────────────────


def extract_images_from_html(html: str) -> list[ImageInfo]:
    """Extract image tags from HTML, returning ImageInfo objects.

    Skips data: URIs and images without a src attribute.
    """
    if not html:
        return []

    results = []

    try:
        from bs4 import BeautifulSoup  # noqa: N814
    except ImportError:
        BeautifulSoup = None  # type: ignore[assignment]  # noqa: N806

    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "html.parser") # type: ignore[operator]
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
            tag_section = html[max(0, alt_pos - 200) : alt_pos + len(src) + 50]
            am = alt_pattern.search(tag_section)
            if am:
                alt = am.group(1)
        results.append(ImageInfo(src=src, alt=alt))

    return results


# ── FR-09: OCR pipeline ───────────────────────────────────────────────────────


def _is_image_file(file_path: str) -> bool:
    ext = Path(file_path).suffix.lower()
    return ext in SUPPORTED_IMAGE_EXTS


def _ocr_with_tesseract(image_path: str, languages: str = "rus+eng") -> OCRResult:
    """Run Tesseract OCR on a single image."""
    pt = _ensure_pytesseract()
    pil_image = _ensure_pil()
    if pt is None:
        raise ImportError("pytesseract not installed")

    img = pil_image.open(image_path) if pil_image is not None else None
    if img is None:
        raise RuntimeError(f"Cannot open image: {image_path}")

    try:
        data = pt.image_to_data(img, lang=languages, output_type=pt.Output.DICT)
    except Exception:
        data = pt.image_to_data(img, lang="eng", output_type=pt.Output.DICT)

    confidences = [int(c) for c in data.get("conf", []) if c != "-1"]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

    blocks = []
    current_block = {"text": "", "conf": 0.0, "lines": []}
    for i in range(len(data.get("text", []))):
        word = data["text"][i].strip()
        conf_val = int(data["conf"][i]) if data["conf"][i] != "-1" else 0
        if word:
            current_block["lines"].append({"word": word, "conf": conf_val})

    if current_block["lines"]:
        confs = [li["conf"] for li in current_block["lines"]]
        current_block["text"] = " ".join(li["word"] for li in current_block["lines"])
        current_block["conf"] = sum(confs) / len(confs) if confs else 0.0
        blocks.append(current_block)

    full_text = pt.image_to_string(img, lang=languages).strip()

    return OCRResult(
        text=full_text,
        confidence=avg_conf,
        language=languages,
        blocks=blocks,
    )


def _ocr_with_easyocr(image_path: str, languages: list[str] | None = None) -> OCRResult:
    """Run EasyOCR on a single image."""
    reader = _ensure_easyocr(languages or ["ru", "en"])
    if reader is None:
        raise ImportError("easyocr not installed")

    results = reader.readtext(image_path)
    confidences = [r[2] for r in results]
    avg_conf = (sum(confidences) / len(confidences) * 100) if confidences else 0.0

    blocks = []
    current_block = {"text": "", "conf": 0.0, "bbox": None, "lines": []}
    for bbox, text, conf in results:
        current_block["lines"].append(
            {"word": text.strip(), "conf": round(conf * 100, 2), "bbox": bbox},
        )
    if current_block["lines"]:
        confs = [li["conf"] for li in current_block["lines"]]
        current_block["text"] = " ".join(li["word"] for li in current_block["lines"])
        current_block["conf"] = sum(confs) / len(confs) if confs else 0.0
        blocks.append(current_block)

    full_text = " ".join(r[1] for r in results).strip()

    return OCRResult(
        text=full_text,
        confidence=avg_conf,
        language=",".join(languages) if languages else "auto",
        blocks=blocks,
    )


def process_image_with_ocr(image_path: str) -> OCRResult | None:
    """Extract text from an image using OCR with fallback strategy.

    Primary: Tesseract OCR (pytesseract) — best for documents.
    Fallback: EasyOCR — better for non-Latin scripts and complex layouts.

    Returns an OCRResult with extracted text and confidence scores,
    or None if OCR is disabled or the image cannot be processed.
    """
    if not OCR_ENABLED:
        logger.debug("OCR is disabled")
        return None

    if not image_path or not os.path.exists(image_path):
        logger.debug("Image not found for OCR: %s", image_path)
        return None

    if not _is_image_file(image_path):
        logger.debug("Not an image file: %s", image_path)
        return None

    primary = OCR_PRIMARY_ENGINE
    default_langs = OCR_LANGUAGES

    if primary == "tesseract":
        try:
            return _ocr_with_tesseract(image_path, languages=default_langs)
        except (ImportError, RuntimeError) as e:
            logger.warning("Tesseract OCR failed (%s), trying EasyOCR fallback", e)
            try:
                result = _ocr_with_easyocr(image_path, languages=["ru", "en"])
                return result
            except (ImportError, RuntimeError) as e2:
                logger.error("EasyOCR fallback also failed: %s", e2)
                return None
    else:
        try:
            result = _ocr_with_easyocr(image_path)
            return result
        except (ImportError, RuntimeError) as e:
            logger.warning("EasyOCR failed (%s), trying Tesseract fallback", e)
            try:
                return _ocr_with_tesseract(image_path, languages=default_langs)
            except (ImportError, RuntimeError) as e2:
                logger.error("Tesseract fallback also failed: %s", e2)
                return None


def process_multi_page_ocr(
    pages: list[str],
    languages: str = "",
) -> list[OCRResult]:
    """Run OCR on multiple pages (TIFF frames, rendered PDF pages).

    Returns a list of OCRResult, one per page.
    """
    results = []
    for i, page_path in enumerate(pages):
        result = process_image_with_ocr(page_path)
        if result is not None:
            result.page_number = i + 1
        else:
            result = OCRResult(text="", confidence=0.0, page_number=i + 1)
        results.append(result)
    return results


# ── FR-10: Image embedding (CLIP) ─────────────────────────────────────────────


def embed_image(image_path: str) -> list[float]:
    """Compute dense CLIP embedding for an image.

    Returns empty list if CLIP is unavailable or image not found.
    """
    if not IMAGE_EXTRACTION_ENABLED:
        return []

    if not image_path or not os.path.exists(image_path):
        logger.debug("Image not found for embedding: %s", image_path)
        return []

    model, processor = _ensure_clip()
    if model is None or processor is None:
        logger.debug("CLIP model not available for %s", image_path)
        return []

    try:
        import torch

        pil_image = _ensure_pil()
        if pil_image is None:
            return []

        image = pil_image.open(image_path).convert("RGB")
        inputs = processor(images=image, return_tensors="pt")
        device = next(model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            image_features = model.get_image_features(**inputs)

        embedding = image_features[0].cpu().tolist()
        logger.debug("Generated embedding (%d dims) for %s", len(embedding), image_path)
        return embedding
    except Exception as e:
        logger.warning("Failed to embed image %s: %s", image_path, e)
        return []


def embed_text(text: str) -> list[float]:
    """Compute CLIP text embedding for cross-modal search."""
    model, processor = _ensure_clip()
    if model is None or processor is None:
        return []

    try:
        import torch

        inputs = processor(text=text, return_tensors="pt", padding=True, truncation=True)
        device = next(model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            text_features = model.get_text_features(**inputs)

        return text_features[0].cpu().tolist()
    except Exception as e:
        logger.warning("Failed to embed text %r: %s", text, e)
        return []


# ── FR-10: Image captioning (BLIP) ────────────────────────────────────────────


def caption_image(image_path: str, alt_text: str = "") -> str:
    """Generate a textual caption for an image using BLIP.

    Falls back to filename/alt-based heuristic if BLIP is unavailable.

    :param image_path: path to the image file
    :param alt_text: optional alt attribute text from HTML
    :return: human-readable caption string
    """
    if not IMAGE_EXTRACTION_ENABLED:
        return _heuristic_caption(image_path, alt_text)

    if not image_path or not os.path.exists(image_path):
        return _heuristic_caption(image_path, alt_text)

    model, processor = _ensure_blip()
    if model is None or processor is None:
        return _heuristic_caption(image_path, alt_text)

    try:
        import torch

        pil_image = _ensure_pil()
        if pil_image is None:
            return _heuristic_caption(image_path, alt_text)

        raw_image = pil_image.open(image_path).convert("RGB")
        inputs = processor(raw_image, return_tensors="pt")
        device = next(model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=50)

        caption = processor.decode(out[0], skip_special_tokens=True).strip()
        if caption:
            logger.debug("BLIP caption for %s: %s", image_path, caption)
            return f"[Image: {caption}]"

    except Exception as e:
        logger.warning("BLIP captioning failed for %s: %s", image_path, e)

    return _heuristic_caption(image_path, alt_text)


def _heuristic_caption(image_path: str, alt_text: str = "") -> str:
    """Heuristic caption fallback using alt text and filename."""
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


# ── FR-10: Cross-modal search utilities ───────────────────────────────────────


def compute_cross_modal_similarity(
    image_embedding: list[float],
    text_embedding: list[float],
) -> float:
    """Compute cosine similarity between image and text CLIP embeddings."""
    if not image_embedding or not text_embedding:
        return 0.0
    if len(image_embedding) != len(text_embedding):
        return 0.0

    dot = sum(a * b for a, b in zip(image_embedding, text_embedding, strict=True))
    norm_a = (sum(a * a for a in image_embedding)) ** 0.5
    norm_b = (sum(b * b for b in text_embedding)) ** 0.5

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_images_by_text(
    query_text: str,
    image_collection_name: str,
    qdrant_client: Any | None = None,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Cross-modal search: text query → image results.

    Requires a Qdrant client and a collection of image vectors.
    """
    if qdrant_client is None:
        logger.warning("No Qdrant client provided for cross-modal image search")
        return []

    text_embedding = embed_text(query_text)
    if not text_embedding:
        return []

    try:
        results = qdrant_client.search(
            collection_name=image_collection_name,
            query_vector=text_embedding,
            limit=top_k,
        )
        return [{"id": r.id, "score": r.score, "payload": r.payload or {}} for r in results]
    except Exception as e:
        logger.warning("Cross-modal search failed: %s", e)
        return []


# ── FR-11: PDF embedded image extraction ──────────────────────────────────────


def extract_images_from_pdf(
    pdf_path: str,
    output_dir: str = "",
    pages: list[int] | None = None,
) -> list[ExtractedImage]:
    """Extract embedded images from a PDF file.

    Uses pdfplumber (primary) or PyMuPDF/fitz (fallback).
    Returns list of ExtractedImage with paths to saved images.

    :param pdf_path: path to the PDF file
    :param output_dir: directory to save extracted images (uses temp dir if empty)
    :param pages: specific page numbers to process (0-indexed), or None for all
    """
    if not os.path.exists(pdf_path):
        logger.warning("PDF not found: %s", pdf_path)
        return []

    if not output_dir:
        output_dir = tempfile.mkdtemp(prefix="pdf_images_")

    extracted = _extract_images_with_pdfplumber(pdf_path, output_dir, pages)
    if not extracted:
        extracted = _extract_images_with_pymupdf(pdf_path, output_dir, pages)

    return extracted


def _extract_images_with_pdfplumber(
    pdf_path: str,
    output_dir: str,
    pages: list[int] | None = None,
) -> list[ExtractedImage]:
    """Extract images using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        return []

    results = []
    try:
        with pdfplumber.open(pdf_path) as pdf_doc:
            target_pages = pages or range(len(pdf_doc.pages))
            for page_num in target_pages:
                if page_num >= len(pdf_doc.pages):
                    continue
                pdf_page = pdf_doc.pages[page_num]
                page_images = pdf_page.images or []
                for img_idx, img_data in enumerate(page_images):
                    image_path = _save_pdfplumber_image(
                        img_data, pdf_doc, page_num, img_idx, output_dir, pdf_path,
                    )
                    if image_path:
                        results.append(
                            ExtractedImage(
                                path=image_path,
                                page_number=page_num + 1,
                                width=img_data.get("width", 0) or 0,
                                height=img_data.get("height", 0) or 0,
                                format=img_data.get("format", "png") or "png",
                                ocr_text="",
                                ocr_confidence=0.0,
                            ),
                        )
    except Exception as e:
        logger.warning("pdfplumber extraction failed for %s: %s", pdf_path, e)

    return results


def _save_pdfplumber_image(
    img_data: dict,
    pdf_doc: Any,
    page_num: int,
    img_idx: int,
    output_dir: str,
    pdf_path: str,
) -> str:
    """Save a pdfplumber page image dict to disk."""
    try:
        pil_image = _ensure_pil()
        if pil_image is None:
            return ""

        page = pdf_doc.pages[page_num]
        # Render page area containing the image
        if "x0" in img_data and "top" in img_data:
            crop = page.within_bbox(
                (img_data["x0"], img_data["top"], img_data["x1"], img_data["bottom"]),
            )
            im = crop.to_image(resolution=150)
        else:
            im = page.to_image(resolution=150)

        filename = f"pdf_{Path(pdf_path).stem}_p{page_num + 1}_img{img_idx}.png"
        filepath = os.path.join(output_dir, filename)
        im.save(filepath)
        return filepath
    except Exception as e:
        logger.debug("Failed to save pdfplumber image: %s", e)
        return ""


def _extract_images_with_pymupdf(
    pdf_path: str,
    output_dir: str,
    pages: list[int] | None = None,
) -> list[ExtractedImage]:
    """Extract images using PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []

    results = []
    try:
        doc = fitz.open(pdf_path)
        target_pages = pages or range(len(doc))
        for page_num in target_pages:
            if page_num >= len(doc):
                continue
            page = doc[page_num]
            image_list = page.get_images(full=True)
            for img_idx, img_info in enumerate(image_list):
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                if base_image is None:
                    continue
                image_bytes = base_image.get("image")
                image_ext = base_image.get("ext", "png")
                if not image_bytes:
                    continue

                filename = f"pdf_{Path(pdf_path).stem}_p{page_num + 1}_img{img_idx}.{image_ext}"
                filepath = os.path.join(output_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(image_bytes)

                results.append(
                    ExtractedImage(
                        path=filepath,
                        page_number=page_num + 1,
                        width=base_image.get("width", 0) or 0,
                        height=base_image.get("height", 0) or 0,
                        format=image_ext,
                        ocr_text="",
                        ocr_confidence=0.0,
                    ),
                )
        doc.close()
    except Exception as e:
        logger.warning("PyMuPDF extraction failed for %s: %s", pdf_path, e)

    return results


def process_pdf_with_ocr(
    pdf_path: str,
    output_dir: str = "",
    pages: list[int] | None = None,
) -> list[ExtractedImage]:
    """Extract images from PDF and run OCR on each.

    Returns list of ExtractedImage with OCR text filled in.
    """
    extracted_images = extract_images_from_pdf(pdf_path, output_dir, pages)
    for img_info in extracted_images:
        ocr_result = process_image_with_ocr(img_info.path)
        if ocr_result is not None:
            img_info.ocr_text = ocr_result.text
            img_info.ocr_confidence = ocr_result.confidence
            img_info.metadata["ocr_confidence"] = ocr_result.confidence
            img_info.metadata["ocr_blocks"] = len(ocr_result.blocks)
    return extracted_images


# ── Quality metrics ───────────────────────────────────────────────────────────


def compute_image_caption_quality(
    image_path: str,
    caption: str,
) -> float:
    """Compute CLIP similarity between image and generated caption as quality score.

    Returns a float in [0, 1].
    """
    if not image_path or not os.path.exists(image_path):
        return 0.0

    img_emb = embed_image(image_path)
    if not img_emb:
        return 0.0

    txt_emb = embed_text(caption)
    if not txt_emb:
        return 0.0

    return compute_cross_modal_similarity(img_emb, txt_emb)
