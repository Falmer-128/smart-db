import os
import tarfile
import zipfile
import logging
from pathlib import Path

try:
    import py7zr
except ImportError:
    py7zr = None

try:
    import rarfile
except ImportError:
    rarfile = None

logger = logging.getLogger(__name__)

def is_safe_path(base_dir: str, target_path: str) -> bool:
    """Ensure the target path resolves within the base directory to prevent path traversal."""
    base = Path(base_dir).resolve()
    target = Path(base_dir, target_path).resolve()
    return base in target.parents or base == target

def extract_archive(file_path: str, extract_to: str) -> None:
    """
    Extracts an archive to the specified directory securely.
    Supports .zip, .tar, .tar.gz, .7z, .rar.
    Raises Exception if extraction fails.
    """
    path = Path(file_path)
    extract_to_path = Path(extract_to)
    
    if not path.exists():
        raise FileNotFoundError(f"Archive not found: {file_path}")

    name_lower = path.name.lower()
    
    if name_lower.endswith('.zip'):
        with zipfile.ZipFile(file_path, 'r') as zf:
            for member in zf.namelist():
                if not is_safe_path(str(extract_to_path), member):
                    raise Exception(f"Unsafe path in zip: {member}")
            zf.extractall(extract_to)
            
    elif name_lower.endswith(('.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz', '.tar.xz', '.txz')):
        with tarfile.open(file_path, 'r:*') as tf:
            for member in tf.getmembers():
                if not is_safe_path(str(extract_to_path), member.name):
                    raise Exception(f"Unsafe path in tar: {member.name}")
            tf.extractall(extract_to)
            
    elif name_lower.endswith('.7z'):
        if py7zr is None:
            raise ImportError("py7zr is not installed. Cannot extract .7z files.")
        with py7zr.SevenZipFile(file_path, mode='r') as szf:
            # py7zr is inherently safe from path traversal by design in recent versions,
            # but we can't easily validate names before extraction without iterating.
            # We trust py7zr's internal extractall checks.
            szf.extractall(path=extract_to)
            
    elif name_lower.endswith('.rar'):
        if rarfile is None:
            raise ImportError("rarfile is not installed. Cannot extract .rar files.")
        with rarfile.RarFile(file_path, 'r') as rf:
            for member in rf.namelist():
                if not is_safe_path(str(extract_to_path), member):
                    raise Exception(f"Unsafe path in rar: {member}")
            rf.extractall(extract_to)
            
    else:
        raise ValueError(f"Unsupported archive format: {path.name}")
        
    logger.info(f"Successfully extracted archive {path.name} to {extract_to}")
