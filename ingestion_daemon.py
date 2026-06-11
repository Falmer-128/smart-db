#!/usr/bin/env python3
"""
Ingestion Daemon — Phase 2 Pipeline Watcher
Continuously polls the INPUT directory for new files every 30 seconds.
Delegates all processing to core.text_processor.process_file (MarkItDown / PaddleOCR / Gemini).
"""

import logging
import time
import sys
from pathlib import Path

from core.ingestion_handler import IngestionHandler

# ── Logging setup ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ingestion_daemon")

def main():
    logger.info("🚀 Starting Ingestion Daemon (Phase 2 Pipeline)")

    base_dir = Path(__file__).parent.resolve()
    input_dir = base_dir / "INPUT"
    processed_dir = base_dir / "PROCESSED"
    output_dir = base_dir / "OUTPUT"

    # Ensure directories exist
    for d in (input_dir, processed_dir, output_dir):
        d.mkdir(parents=True, exist_ok=True)
        logger.info(f"Verified directory: {d}")

    # Initialize handler — no legacy Deduplicator needed;
    # text_processor.SemanticHasher handles dedup internally.
    handler = IngestionHandler(
        input_dir=str(input_dir),
        processed_dir=str(processed_dir),
        output_dir=str(output_dir),
    )

    logger.info(f"👀 Now polling {input_dir} every 30 seconds for new files...")

    try:
        while True:
            # Find all non-hidden files in INPUT
            files = [f for f in input_dir.iterdir() if f.is_file() and not f.name.startswith('.')]

            if files:
                logger.info(f"Found {len(files)} file(s) to process.")
                for file_path in files:
                    try:
                        handler.process_file(Path(file_path))
                    except Exception as e:
                        logger.error(f"Error processing {file_path.name}: {e}", exc_info=True)
            else:
                logger.debug("No files found in INPUT directory.")

            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("🛑 Daemon interrupted by user. Shutting down...")
    except Exception as e:
        logger.critical(f"💥 Daemon crashed: {e}", exc_info=True)

    logger.info("Daemon gracefully exited.")

if __name__ == "__main__":
    main()
