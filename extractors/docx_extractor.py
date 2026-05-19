"""
Word (.docx) document text extraction using python-docx.
"""

from __future__ import annotations

import logging

import docx

logger = logging.getLogger(__name__)


def extract(file_path: str) -> str:
    """
    Extract all non-empty paragraphs from a DOCX file.

    Returns
    -------
    str
        Plain-text representation of the document.

    Raises
    ------
    RuntimeError
        When python-docx cannot open or parse the file.
    """
    logger.info("Extracting text from DOCX: '%s'.", file_path)

    try:
        document = docx.Document(file_path)
    except Exception as exc:
        raise RuntimeError(
            f"python-docx failed to open '{file_path}': {exc}"
        ) from exc

    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    result = "\n".join(paragraphs)
    logger.info("DOCX extraction complete — %d paragraphs.", len(paragraphs))
    return result
