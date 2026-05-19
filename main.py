#!/usr/bin/env python3
"""
Smart Document Parser — ETL entry point.

Orchestrates the full pipeline:
  1. Ensure directories exist.
  2. Scan INPUT for new documents.
  3. Route each file to the appropriate extractor.
  4. Save extracted text to PROCESSED.
  5. Print a summary report.
"""

from __future__ import annotations

import logging
import sys

from core.router import route
from utils.file_manager import ensure_directories, list_new_files, save_text

# ── Logging setup ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("smart_parser")


def main() -> None:
    """Run the ETL pipeline."""
    logger.info("🚀 Starting Smart Document Parser")
    ensure_directories()

    new_files = list_new_files()
    if not new_files:
        logger.info("No new files to process. Exiting.")
        return

    logger.info("Found %d new file(s) to process.", len(new_files))

    processed_count = 0
    error_count = 0

    for file_path in new_files:
        logger.info("📄 Processing: %s", file_path.name)

        try:
            text = route(str(file_path))
        except Exception:
            logger.error(
                "❌ Failed to extract '%s'.", file_path.name, exc_info=True
            )
            error_count += 1
            continue

        if text is None:
            logger.warning(
                "⚠️  No text could be extracted from '%s'.", file_path.name
            )
            error_count += 1
            continue

        save_text(file_path, text)
        processed_count += 1
        logger.info("✅ Added to knowledge base: %s", file_path.name)

    # ── Summary ──────────────────────────────────────────────
    logger.info("=" * 40)
    logger.info("🏁 Pipeline complete")
    logger.info("   New texts added : %d", processed_count)
    logger.info("   Errors / skipped: %d", error_count)
    logger.info("=" * 40)

    if error_count:
        sys.exit(1)


if __name__ == "__main__":
    main()
