import logging
import os
import shutil
import time
from pathlib import Path
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from .archive_extractor import extract_archive
from .deduplicator import Deduplicator

logger = logging.getLogger(__name__)

def wait_for_file_to_stabilize(file_path: Path, wait_time: float = 1.0, retries: int = 5) -> bool:
    """
    Debounce mechanism to ensure a file is completely written and unlocked by the OS.
    Returns True if the file is stable and ready, False otherwise.
    """
    if file_path.name.endswith(('.crdownload', '.part', '.tmp')):
        logger.debug(f"Ignoring temporary file: {file_path.name}")
        return False

    previous_size = -1
    for attempt in range(retries):
        if not file_path.exists():
            return False
            
        try:
            current_size = os.path.getsize(file_path)
            
            # If size changed, it's still being written
            if current_size != previous_size:
                previous_size = current_size
                time.sleep(wait_time)
                continue
                
            # Size is stable, now check if OS lock is released by trying to open it
            with open(file_path, 'rb'):
                pass
                
            # If we reached here, size is stable and file is readable
            return True
            
        except OSError:
            # File might be locked by another process (e.g. still copying/downloading)
            time.sleep(wait_time)
            
    logger.warning(f"File {file_path.name} did not stabilize after {retries} retries.")
    return False

class IngestionHandler(FileSystemEventHandler):
    def __init__(self, input_dir: str, processed_dir: str, output_dir: str, deduplicator: Deduplicator):
        super().__init__()
        self.input_dir = Path(input_dir)
        self.processed_dir = Path(processed_dir)
        self.output_dir = Path(output_dir)
        self.deduplicator = deduplicator
        self.processing_files = set()
        
        # Extensions considered as archives
        self.archive_exts = {'.zip', '.tar', '.gz', '.tgz', '.bz2', '.tbz', '.xz', '.txz', '.7z', '.rar'}

    def process_file(self, file_path: Path) -> None:
        if not file_path.is_file():
            return

        abs_path = str(file_path.absolute())
        if abs_path in self.processing_files:
            return
            
        self.processing_files.add(abs_path)
        try:
            if not wait_for_file_to_stabilize(file_path):
                return
                
            if not file_path.exists():
                return

            logger.info(f"Processing new file: {file_path.name}")
            
            # Check if it's an archive
            if any(file_path.name.lower().endswith(ext) for ext in self.archive_exts):
                logger.info(f"Archive detected: {file_path.name}. Extracting...")
                extract_archive(str(file_path), str(self.input_dir))
                logger.info(f"Extraction successful. Deleting original archive: {file_path.name}")
                os.remove(file_path)
                return
            else:
                # Handle standard file with deduplication
                logger.info(f"Checking for duplicates: {file_path.name}")
                if self.deduplicator.is_duplicate(str(file_path)):
                    logger.warning(f"Duplicate detected. Deleting: {file_path.name}")
                    os.remove(file_path)
                else:
                    dest_path = self.processed_dir / file_path.name
                    logger.info(f"New file. Moving to PROCESSED: {dest_path.name}")
                    
                    # Handle name collisions in PROCESSED by appending timestamp
                    if dest_path.exists():
                        base = dest_path.stem
                        ext = dest_path.suffix
                        timestamp = int(time.time())
                        dest_path = self.processed_dir / f"{base}_{timestamp}{ext}"
                    
                    shutil.move(str(file_path), str(dest_path))

        except FileNotFoundError:
            logger.warning(f"File {file_path.name} disappeared before processing could complete.")
            pass
        except Exception as e:
            logger.error(f"Error processing {file_path.name}: {e}", exc_info=True)
            try:
                dest_path = self.output_dir / file_path.name
                # Handle collisions in OUTPUT as well
                if dest_path.exists():
                    base = dest_path.stem
                    ext = dest_path.suffix
                    timestamp = int(time.time())
                    dest_path = self.output_dir / f"{base}_{timestamp}{ext}"
                
                logger.error(f"Quarantining file {file_path.name} to {dest_path.name}")
                shutil.move(str(file_path), str(dest_path))
            except Exception as quarantine_e:
                logger.critical(f"FATAL: Failed to quarantine {file_path.name}: {quarantine_e}")
        finally:
            self.processing_files.discard(abs_path)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.process_file(Path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.process_file(Path(event.dest_path))
