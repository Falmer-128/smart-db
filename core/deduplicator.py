import hashlib
import json
import logging
from pathlib import Path
from typing import Set

logger = logging.getLogger(__name__)

class Deduplicator:
    def __init__(self, db_path: str = "seen_hashes.json"):
        self.db_path = Path(db_path)
        self.seen_hashes: Set[str] = set()
        self._load()

    def _load(self) -> None:
        """Loads existing hashes from the JSON file."""
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.seen_hashes = set(data)
                    else:
                        logger.warning(f"Unexpected format in {self.db_path}, starting fresh.")
            except Exception as e:
                logger.error(f"Failed to load {self.db_path}: {e}")
        else:
            logger.info(f"No existing hash DB found at {self.db_path}. A new one will be created.")

    def _save(self) -> None:
        """Saves current hashes to the JSON file."""
        try:
            with open(self.db_path, 'w') as f:
                json.dump(list(self.seen_hashes), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save {self.db_path}: {e}")

    def compute_hash(self, file_path: str) -> str:
        """Computes the MD5 hash of a file."""
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            # Read in chunks to handle large files efficiently
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def is_duplicate(self, file_path: str) -> bool:
        """
        Checks if a file is a duplicate based on its MD5 hash.
        If it's a new file, its hash is added to the DB and saved.
        """
        file_hash = self.compute_hash(file_path)
        if file_hash in self.seen_hashes:
            return True
        
        self.seen_hashes.add(file_hash)
        self._save()
        return False
