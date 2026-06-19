#!/usr/bin/env python3
import os
import shutil
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "INPUT")
OUTPUT_DIR = os.path.join(BASE_DIR, "OUTPUT")

VALID_EXTS = ('.xlsx', '.xls', '.pdf', '.docx', '.zip', '.7z', '.tar', '.tar.gz')


def run_rescue():
    if not os.path.exists(OUTPUT_DIR):
        logging.info(f"Quarantine directory does not exist: {OUTPUT_DIR}")
        return

    os.makedirs(INPUT_DIR, exist_ok=True)

    recovered_count = 0
    ignored_count = 0

    for filename in os.listdir(OUTPUT_DIR):
        # ── Exclusion Logic ──────────────────────────────────────────────
        if filename.startswith("~$") or filename.startswith(".") or filename.endswith(".lnk"):
            ignored_count += 1
            continue

        # ── Extension Check (case-insensitive) ───────────────────────────
        if not filename.lower().endswith(VALID_EXTS):
            ignored_count += 1
            continue

        src = os.path.join(OUTPUT_DIR, filename)
        dst = os.path.join(INPUT_DIR, filename)

        try:
            shutil.move(src, dst)
            recovered_count += 1
            logging.info(f"✅ Rescued: {filename}")
        except Exception as e:
            logging.error(f"❌ Failed to rescue {filename}: {e}")

    # ── Final Summary ────────────────────────────────────────────────────
    logging.info("")
    logging.info("═" * 40)
    logging.info(f"  Recovered: {recovered_count}")
    logging.info(f"  Ignored:   {ignored_count}")
    logging.info("═" * 40)


if __name__ == "__main__":
    run_rescue()
