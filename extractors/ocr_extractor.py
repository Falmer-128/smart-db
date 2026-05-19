"""
Heavy-path OCR extraction for scanned / image-only PDFs.

Uses pdf2image to rasterize pages and pytesseract to recognize text.
Language packs and DPI are pulled from config.
"""

from __future__ import annotations

import logging

import pytesseract
from pdf2image import convert_from_path

from config import OCR_DPI, OCR_LANGUAGES

logger = logging.getLogger(__name__)


def extract(file_path: str) -> str:
    """
    Convert every page of a PDF to an image and run Tesseract OCR.

    Returns
    -------
    str
        Concatenated OCR text with page separators.

    Raises
    ------
    RuntimeError
        When pdf2image or pytesseract fails irrecoverably.
    """
    logger.info(
        "Starting OCR (lang=%s, dpi=%d) on '%s'.",
        OCR_LANGUAGES,
        OCR_DPI,
        file_path,
    )

    try:
        pages = convert_from_path(file_path, dpi=OCR_DPI)
    except Exception as exc:
        raise RuntimeError(
            f"pdf2image failed to rasterize '{file_path}': {exc}"
        ) from exc

    full_text: list[str] = []

    for idx, page_image in enumerate(pages, start=1):
        try:
            text = pytesseract.image_to_string(page_image, lang=OCR_LANGUAGES)
            full_text.append(f"--- PAGE {idx} ---\n{text}")
        except Exception:
            logger.error(
                "Tesseract failed on page %d of '%s'.",
                idx,
                file_path,
                exc_info=True,
            )
            full_text.append(f"--- PAGE {idx} ---\n[OCR ERROR]\n")

    result = "\n\n".join(full_text).strip()
    logger.info("OCR complete — %d pages, %d chars.", len(pages), len(result))
    return result
