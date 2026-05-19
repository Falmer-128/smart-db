"""
File-management utilities.

Responsibilities:
  • Scan the INPUT directory for new documents.
  • Enforce **idempotency** — skip files already present in PROCESSED.
  • Save extracted text to disk.
  • Ensure all required directories exist on startup.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from config import INPUT_DIR, OUTPUT_DIR, PROCESSED_DIR, SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


def ensure_directories() -> None:
    """Create INPUT / PROCESSED / OUTPUT directories if they do not exist."""
    for directory in (INPUT_DIR, PROCESSED_DIR, OUTPUT_DIR):
        os.makedirs(directory, exist_ok=True)
        logger.debug("Directory ensured: '%s'.", directory)


def list_new_files() -> list[Path]:
    """
    Return a list of files in INPUT_DIR that:
      1. Have a supported extension.
      2. Have **not** already been processed (no matching .txt in PROCESSED_DIR).
      3. Are not hidden (do not start with '.').

    Returns
    -------
    list[Path]
        Absolute paths to files that need processing.
    """
    input_path = Path(INPUT_DIR)
    if not input_path.is_dir():
        logger.error("INPUT_DIR '%s' does not exist.", INPUT_DIR)
        return []

    new_files: list[Path] = []

    for entry in sorted(input_path.iterdir()):
        if not entry.is_file():
            continue
        if entry.name.startswith("."):
            continue
        if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
            logger.debug("Skipping unsupported file: '%s'.", entry.name)
            continue

        processed_path = _get_processed_path(entry)
        if processed_path.exists():
            logger.info(
                "Skipping '%s' — already in knowledge base.", entry.name
            )
            continue

        new_files.append(entry)

    return new_files


def save_text(source_file: Path, text: str) -> Path:
    """
    Persist *text* into the PROCESSED directory, using the source
    file's base name with a ``.txt`` extension.

    Returns
    -------
    Path
        Path to the saved file.
    """
    dest = _get_processed_path(source_file)
    dest.write_text(text, encoding="utf-8")
    logger.info("Saved processed text → '%s'.", dest)
    return dest


def _get_processed_path(source_file: Path) -> Path:
    """Derive the corresponding .txt path inside PROCESSED_DIR."""
    return Path(PROCESSED_DIR) / f"{source_file.stem}.txt"
