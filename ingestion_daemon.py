#!/usr/bin/env python3
import os
import time
import shutil
import logging
import zipfile
import tarfile
from dotenv import load_dotenv
from pathlib import Path
import sys

try:
    import py7zr
except ImportError:
    py7zr = None

try:
    import rarfile
except ImportError:
    rarfile = None

_project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_project_root))

from core.text_processor import process_file

dotenv_path = _project_root / ".env"
load_dotenv(dotenv_path)

INPUT_DIR = str(_project_root / "INPUT")
CHUNKS_DIR = str(_project_root / "CHUNKS_STAGING")
PROCESSED_DIR = str(_project_root / "PROCESSED")
OUTPUT_DIR = str(_project_root / "OUTPUT")       # Quarantine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("ingestion.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

VALID_ARCHIVES = ('.zip', '.tar.gz', '.tar', '.7z', '.rar')


def _detect_archive_ext(filename):
    """Return the matching archive extension or None."""
    lower = filename.lower()
    # Check compound extension first
    if lower.endswith('.tar.gz'):
        return '.tar.gz'
    for ext in VALID_ARCHIVES:
        if lower.endswith(ext):
            return ext
    return None


def _extract_archive(filepath, ext, dest_dir):
    """Extract an archive into *dest_dir* using the correct tool."""
    if ext == '.zip':
        with zipfile.ZipFile(filepath, 'r') as zf:
            zf.extractall(dest_dir)

    elif ext in ('.tar', '.tar.gz'):
        with tarfile.open(filepath, 'r:*') as tf:
            tf.extractall(dest_dir)

    elif ext == '.7z':
        if py7zr is None:
            raise ImportError("py7zr is not installed — cannot extract .7z archives")
        with py7zr.SevenZipFile(filepath, mode='r') as sz:
            sz.extractall(path=dest_dir)

    elif ext == '.rar':
        if rarfile is None:
            raise ImportError("rarfile is not installed — cannot extract .rar archives")
        with rarfile.RarFile(filepath, 'r') as rf:
            rf.extractall(dest_dir)

    else:
        raise ValueError(f"Unsupported archive extension: {ext}")


def main():
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(CHUNKS_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    logging.info(f"Started ingestion daemon. Monitoring {INPUT_DIR}")

    while True:
        try:
            for dirpath, dirnames, filenames in os.walk(INPUT_DIR):
                # Skip hidden directories
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for filename in filenames:
                    # Skip hidden files and Office lock files
                    if filename.startswith(".") or filename.startswith("~$"):
                        continue

                    filepath = os.path.join(dirpath, filename)

                    # ── Archive detection (BEFORE text processing) ──
                    archive_ext = _detect_archive_ext(filename)
                    if archive_ext is not None:
                        logging.info(f"Archive detected: {filename} (type: {archive_ext})")
                        extract_dir = os.path.join(dirpath, f"{filename}_extracted")
                        os.makedirs(extract_dir, exist_ok=True)
                        try:
                            _extract_archive(filepath, archive_ext, extract_dir)
                            logging.info(f"Successfully extracted {filename} → {extract_dir}")
                            shutil.move(filepath, os.path.join(PROCESSED_DIR, filename))
                            logging.info(f"Moved original archive {filename} → PROCESSED/")
                        except Exception as e:
                            logging.error(f"Failed to extract {filename}: {e}")
                            shutil.move(filepath, os.path.join(OUTPUT_DIR, filename))
                            logging.info(f"Quarantined {filename} → OUTPUT/")
                        continue  # Do NOT send archive to the text parsing pipeline

                    # ── Regular file → OCR / text processing ────────
                    logging.info(f"Ingesting {filename} via OCR...")
                    try:
                        # process_file handles Docling OCR, outputs JSON to CHUNKS_STAGING, and moves original to PROCESSED
                        process_file(filepath, save_to_disk=True, enable_tier3=True)
                        logging.info(f"Successfully processed {filename}.")
                    except Exception as e:
                        logging.error(f"Failed to process {filename}: {e}")

            # Clean up empty directories left behind after processing
            for dirpath, dirnames, filenames in os.walk(INPUT_DIR, topdown=False):
                if dirpath == INPUT_DIR:
                    continue
                try:
                    os.rmdir(dirpath)
                    logging.info(f"Removed empty directory: {dirpath}")
                except OSError:
                    pass  # Directory not empty, skip

        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")

        time.sleep(5)


if __name__ == "__main__":
    main()
