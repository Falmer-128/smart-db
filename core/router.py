"""
Router — inspects a file and delegates it to the correct extractor.

Routing decision tree:
  1. Check file extension.
  2. For PDFs → try fast text-layer extraction first.
     If the text layer is absent / too thin → fall back to OCR.
  3. For DOCX → docx_extractor.
  4. For XLSX/XLS → excel_extractor.
  5. Anything else → log a warning, return None.
"""

from __future__ import annotations

import logging
from pathlib import Path

from extractors import (
    docx_extractor,
    excel_extractor,
    ocr_extractor,
    pdf_extractor,
)

logger = logging.getLogger(__name__)


def route(file_path: str) -> str | None:
    """
    Determine the correct extractor for *file_path* and return the
    extracted text.

    Returns
    -------
    str | None
        Extracted text on success; ``None`` when the format is
        unsupported.
    """
    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        logger.info("Routing '%s' → PDF pipeline.", file_path)
        text = pdf_extractor.extract(file_path)
        if text is not None:
            return text
        # Text layer missing or too short — escalate to OCR
        logger.info("Escalating '%s' to OCR.", file_path)
        return ocr_extractor.extract(file_path)

    if ext == ".docx":
        logger.info("Routing '%s' → DOCX extractor.", file_path)
        return docx_extractor.extract(file_path)

    if ext in {".xlsx", ".xls"}:
        logger.info("Routing '%s' → Excel extractor.", file_path)
        return excel_extractor.extract(file_path)

    logger.warning("Unsupported file format '%s' for '%s'.", ext, file_path)
    return None
