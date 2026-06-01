#!/usr/bin/env python3
"""
Ingestion, Extraction, and Triage Daemon (Phase 1)
Continuously monitors the INPUT directory for new files and archives.
"""

import logging
import time
import sys
from pathlib import Path
from watchdog.observers import Observer

from core.deduplicator import Deduplicator
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
    logger.info("🚀 Starting Ingestion, Extraction, and Triage Daemon")

    base_dir = Path(__file__).parent.resolve()
    input_dir = base_dir / "INPUT"
    processed_dir = base_dir / "PROCESSED"
    output_dir = base_dir / "OUTPUT"

    # Ensure directories exist
    for d in (input_dir, processed_dir, output_dir):
        d.mkdir(parents=True, exist_ok=True)
        logger.info(f"Verified directory: {d}")

    # Initialize components
    deduplicator = Deduplicator(db_path=str(base_dir / "seen_hashes.json"))
    handler = IngestionHandler(
        input_dir=str(input_dir),
        processed_dir=str(processed_dir),
        output_dir=str(output_dir),
        deduplicator=deduplicator
    )

    # Set up watchdog
    observer = Observer()
    observer.schedule(handler, str(input_dir), recursive=False)
    observer.start()
    
    logger.info(f"👀 Now monitoring {input_dir} for new files...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("🛑 Daemon interrupted by user. Shutting down...")
        observer.stop()
    except Exception as e:
        logger.critical(f"💥 Daemon crashed: {e}", exc_info=True)
        observer.stop()
    
    observer.join()
    logger.info("Daemon gracefully exited.")

if __name__ == "__main__":
    main()
