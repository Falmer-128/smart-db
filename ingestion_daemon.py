#!/usr/bin/env python3
import os
import time
import logging
from dotenv import load_dotenv
from pathlib import Path
import sys

_project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_project_root))

from core.text_processor import process_file

dotenv_path = _project_root / ".env"
load_dotenv(dotenv_path)

INPUT_DIR = str(_project_root / "INPUT")
CHUNKS_DIR = str(_project_root / "CHUNKS_STAGING")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("ingestion.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

def main():
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(CHUNKS_DIR, exist_ok=True)
    
    logging.info(f"Started ingestion daemon. Monitoring {INPUT_DIR}")

    while True:
        try:
            for filename in os.listdir(INPUT_DIR):
                if filename.startswith("."):
                    continue
                
                filepath = os.path.join(INPUT_DIR, filename)
                
                if not os.path.isfile(filepath):
                    continue

                logging.info(f"Ingesting {filename} via OCR...")
                try:
                    # process_file handles Docling OCR, outputs JSON to CHUNKS_STAGING, and moves original to PROCESSED
                    process_file(filepath, save_to_disk=True, enable_tier3=True)
                    logging.info(f"Successfully processed {filename}.")
                except Exception as e:
                    logging.error(f"Failed to process {filename}: {e}")
                        
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")
            
        time.sleep(5)

if __name__ == "__main__":
    main()
