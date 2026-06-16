#!/usr/bin/env python3
"""
upload_daemon.py – Uploads processed JSON chunks to AnythingLLM.

This daemon is started by the orchestrator ONLY during LLM mode,
when the AnythingLLM container is running. It must NOT run during
OCR mode (Docker/VRAM is needed for Docling).
"""
import os
import sys
import json
import time
import shutil
import logging
import tempfile
import requests
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
_project_root = Path(__file__).resolve().parent
dotenv_path = _project_root / ".env"
if not dotenv_path.exists():
    dotenv_path = Path.home() / ".env"
load_dotenv(dotenv_path)

API_KEY = os.environ.get("ANYTHINGLLM_API_KEY")
if not API_KEY:
    logging.critical(
        "ANYTHINGLLM_API_KEY is not set or empty in .env. Exiting."
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = "http://127.0.0.1:3001/api/v1"
WORKSPACE_SLUG = "dokumenty"
STAGING_DIR = _project_root / "CHUNKS_STAGING"
ARCHIVE_DIR = _project_root / "ARCHIVED"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("upload.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("upload_daemon")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text_from_chunks(filepath: Path) -> str:
    """Read a JSON chunk file (list of dicts) and return merged text."""
    with open(filepath, "r", encoding="utf-8") as f:
        chunks = json.load(f)
    texts = [
        chunk["text"]
        for chunk in chunks
        if isinstance(chunk, dict) and "text" in chunk
    ]
    return "\n\n".join(texts)


def _upload_document(tmp_path: str, display_name: str) -> str | None:
    """Upload a .txt file to AnythingLLM. Returns the location or None."""
    with open(tmp_path, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/document/upload",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Accept": "application/json",
            },
            files={"file": (display_name, f, "text/plain")},
        )

    if response.status_code != 200:
        logger.error(
            "Upload failed for %s – HTTP %s: %s",
            display_name, response.status_code, response.text,
        )
        return None

    data = response.json()
    documents = data.get("documents", [])
    if documents and isinstance(documents, list) and len(documents) > 0:
        location = documents[0].get("location")
        if location:
            return location
        logger.error("Upload OK but no location in response for %s", display_name)
    else:
        logger.error("Upload OK but 'documents' missing for %s", display_name)
    return None


def _embed_document(location: str, display_name: str) -> bool:
    """Trigger workspace embedding for a previously uploaded document."""
    response = requests.post(
        f"{BASE_URL}/workspace/{WORKSPACE_SLUG}/update-embeddings",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={"adds": [location], "deletes": []},
    )
    if response.status_code == 200:
        logger.info("Successfully embedded %s.", display_name)
        return True
    logger.error(
        "Embedding failed for %s – HTTP %s: %s",
        display_name, response.status_code, response.text,
    )
    return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Started upload daemon. Monitoring %s", STAGING_DIR)

    while True:
        try:
            for json_file in sorted(STAGING_DIR.glob("*.json")):
                tmp_path = None
                try:
                    # --- Extract text from JSON chunks -----------------------
                    text = _extract_text_from_chunks(json_file)
                    if not text.strip():
                        logger.warning("No text extracted from %s – skipping.", json_file.name)
                        continue

                    # --- Write to a temporary .txt file ----------------------
                    txt_name = json_file.stem + ".txt"
                    fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="upload_")
                    with os.fdopen(fd, "w", encoding="utf-8") as tmp_f:
                        tmp_f.write(text)

                    # --- Upload ----------------------------------------------
                    logger.info("Uploading %s ...", json_file.name)
                    location = _upload_document(tmp_path, txt_name)
                    if location is None:
                        continue

                    # --- Embed -----------------------------------------------
                    if not _embed_document(location, json_file.name):
                        continue

                    # --- Archive original JSON on full success ----------------
                    archive_path = ARCHIVE_DIR / json_file.name
                    shutil.move(str(json_file), str(archive_path))
                    logger.info("Archived %s.", json_file.name)

                except json.JSONDecodeError as exc:
                    logger.error("Invalid JSON in %s: %s", json_file.name, exc)
                except requests.exceptions.RequestException as exc:
                    logger.error("Network error processing %s: %s", json_file.name, exc)
                except Exception as exc:
                    logger.error("Unexpected error processing %s: %s", json_file.name, exc)
                finally:
                    # Always clean up the temp file
                    if tmp_path and os.path.exists(tmp_path):
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass

        except Exception as exc:
            logger.error("Unexpected error in main loop: %s", exc)

        time.sleep(10)


if __name__ == "__main__":
    main()
