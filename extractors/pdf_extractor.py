"""
Fast text-layer PDF extraction using pypdf.

Falls back gracefully — returns None when the text layer is absent
or too short (below the configured threshold), signalling the router
to escalate to OCR.
"""

from __future__ import annotations

import logging
from pypdf import PdfReader

from config import PDF_TEXT_THRESHOLD

logger = logging.getLogger(__name__)


def extract(file_path: str) -> str | None:
    """
    Attempt to extract text from a PDF that has an embedded text layer.

    Returns
    -------
    str | None
        Extracted text if the layer is present and above the character
        threshold; ``None`` otherwise.
    """
    try:
        reader = PdfReader(file_path)
        pages_text: list[str] = []

        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)

        full_text = "\n".join(pages_text).strip()

        if len(full_text) >= PDF_TEXT_THRESHOLD:
            logger.info("Text layer detected (%d chars).", len(full_text))
            return full_text

        logger.info(
            "Text layer too short (%d chars < threshold %d). "
            "Deferring to OCR.",
            len(full_text),
            PDF_TEXT_THRESHOLD,
        )
        return None

    except Exception:
        logger.warning(
            "pypdf could not read '%s'. Deferring to OCR.",
            file_path,
            exc_info=True,
        )
        return None
