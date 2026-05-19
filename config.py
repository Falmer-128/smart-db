"""
Centralized configuration management.

Loads settings from environment variables / .env file and exposes
them as module-level constants. All other modules import from here
instead of reading os.environ directly.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (if present)
load_dotenv(Path(__file__).resolve().parent / ".env")

# ── Directory paths ──────────────────────────────────────────
INPUT_DIR: str = os.getenv("INPUT_DIR", "INPUT")
PROCESSED_DIR: str = os.getenv("PROCESSED_DIR", "PROCESSED")
OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "OUTPUT")

# ── OCR settings ─────────────────────────────────────────────
OCR_LANGUAGES: str = os.getenv("OCR_LANGUAGES", "rus+eng")
OCR_DPI: int = int(os.getenv("OCR_DPI", "300"))

# ── Processing thresholds ────────────────────────────────────
PDF_TEXT_THRESHOLD: int = int(os.getenv("PDF_TEXT_THRESHOLD", "50"))

# ── Supported file extensions ────────────────────────────────
SUPPORTED_EXTENSIONS: set[str] = {".pdf", ".docx", ".doc", ".xlsx", ".xls"}
