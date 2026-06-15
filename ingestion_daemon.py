#!/usr/bin/env python3
import os
import sys
import time
import shutil
import logging
import requests
from dotenv import load_dotenv

dotenv_path = os.path.expanduser("~/smart-db/.env")
load_dotenv(dotenv_path)

API_KEY = os.environ.get("ANYTHINGLLM_API_KEY")

if not API_KEY:
    logging.critical("ANYTHINGLLM_API_KEY is not set or empty in .env. Exiting.")
    sys.exit(1)
BASE_URL = "http://127.0.0.1:3001/api/v1"
WORKSPACE_SLUG = "dokumenty"
STAGING_DIR = os.path.expanduser("~/smart-db/CHUNKS_STAGING")
ARCHIVE_DIR = os.path.expanduser("~/smart-db/ARCHIVED")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

def main():
    os.makedirs(STAGING_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    
    logging.info(f"Started ingestion daemon. Monitoring {STAGING_DIR}")

    while True:
        try:
            for filename in os.listdir(STAGING_DIR):
                if not filename.endswith(".md"):
                    continue
                
                filepath = os.path.join(STAGING_DIR, filename)
                
                # Upload Step
                logging.info(f"Processing {filename}...")
                upload_success = False
                location = None
                
                try:
                    with open(filepath, "rb") as f:
                        response = requests.post(
                            f"{BASE_URL}/document/upload",
                            headers={
                                "Authorization": f"Bearer {API_KEY}",
                                "Accept": "application/json"
                            },
                            files={"file": (filename, f, "text/markdown")}
                        )
                        
                    if response.status_code == 200:
                        data = response.json()
                        documents = data.get("documents", [])
                        if documents and isinstance(documents, list) and len(documents) > 0:
                            location = documents[0].get("location")
                            if location:
                                upload_success = True
                            else:
                                logging.error(f"Upload succeeded but no location found for {filename}")
                        else:
                            logging.error(f"Upload succeeded but 'documents' missing for {filename}")
                    else:
                        logging.error(f"Failed to upload {filename}. HTTP {response.status_code}: {response.text}")
                except requests.RequestException as e:
                    logging.error(f"Network error during upload of {filename}: {e}")
                    
                if not upload_success or not location:
                    continue
                
                # Embed Step
                embed_success = False
                try:
                    embed_response = requests.post(
                        f"{BASE_URL}/workspace/{WORKSPACE_SLUG}/update-embeddings",
                        headers={
                            "Authorization": f"Bearer {API_KEY}",
                            "Content-Type": "application/json",
                            "Accept": "application/json"
                        },
                        json={"adds": [location], "deletes": []}
                    )
                    
                    if embed_response.status_code == 200:
                        logging.info(f"Successfully embedded {filename}.")
                        embed_success = True
                    else:
                        logging.error(f"Failed to embed {filename}. HTTP {embed_response.status_code}: {embed_response.text}")
                except requests.RequestException as e:
                    logging.error(f"Network error during embedding of {filename}: {e}")
                    
                # Cleanup Step
                if upload_success and embed_success:
                    archive_path = os.path.join(ARCHIVE_DIR, filename)
                    try:
                        shutil.move(filepath, archive_path)
                        logging.info(f"Moved {filename} to archive.")
                    except Exception as e:
                        logging.error(f"Failed to move {filename} to archive: {e}")
                        
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")
            
        time.sleep(10)

if __name__ == "__main__":
    main()
