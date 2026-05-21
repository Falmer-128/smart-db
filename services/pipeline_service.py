"""
Pipeline Service — the single API boundary between any UI and the core.

Every user-facing operation (listing files, processing documents,
reading previews) goes through this class.  The TUI, a future Web UI,
or even a CLI script should import *only* this module, never the
extractors or file_manager directly.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from config import INPUT_DIR, OUTPUT_DIR, PROCESSED_DIR, SUPPORTED_EXTENSIONS
from core.router import route
from utils.file_manager import ensure_directories, save_text

from services.models import (
    BatchResult,
    FileInfo,
    FileStatus,
    FileType,
    PipelineStats,
    ProcessResult,
)

logger = logging.getLogger(__name__)

# Maximum number of characters to read for a file preview.
_PREVIEW_MAX_CHARS: int = 8_000


class PipelineService:
    """
    Stateless facade over the smart-db ETL pipeline.

    All methods are safe to call from an async context via
    ``asyncio.to_thread`` (they do filesystem / CPU work, never
    hold shared mutable state).
    """

    # ── Directory queries ────────────────────────────────────

    @staticmethod
    def ensure_directories() -> None:
        """Create INPUT / PROCESSED / OUTPUT dirs if missing."""
        ensure_directories()

    @staticmethod
    def list_input_files() -> list[FileInfo]:
        """
        Return metadata for every supported file in INPUT/.

        Files that already have a matching .txt in PROCESSED/ are
        marked as ``FileStatus.PROCESSED``; the rest are ``PENDING``.
        """
        input_path = Path(INPUT_DIR)
        if not input_path.is_dir():
            return []

        results: list[FileInfo] = []
        for entry in sorted(input_path.iterdir()):
            if not entry.is_file() or entry.name.startswith("."):
                continue
            if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            # Check idempotency
            processed = Path(PROCESSED_DIR) / f"{entry.stem}.txt"
            status = (
                FileStatus.PROCESSED if processed.exists() else FileStatus.PENDING
            )
            results.append(FileInfo.from_path(entry, status=status))

        return results

    @staticmethod
    def list_processed_files() -> list[FileInfo]:
        """Return metadata for every .txt file in PROCESSED/."""
        proc_path = Path(PROCESSED_DIR)
        if not proc_path.is_dir():
            return []

        results: list[FileInfo] = []
        for entry in sorted(proc_path.iterdir()):
            if not entry.is_file() or entry.name.startswith("."):
                continue
            if entry.suffix.lower() != ".txt":
                continue
            results.append(
                FileInfo.from_path(entry, status=FileStatus.PROCESSED)
            )

        return results

    # ── File preview ─────────────────────────────────────────

    @staticmethod
    def get_file_preview(file_path: str | Path, max_chars: int = _PREVIEW_MAX_CHARS) -> str:
        """
        Read the first *max_chars* characters of a file for preview.

        For binary/non-text files returns a placeholder message.
        """
        path = Path(file_path)

        if not path.exists():
            return f"[File not found: {path.name}]"

        # For supported source documents, show metadata only
        ext = path.suffix.lower()
        if ext in {".pdf", ".docx", ".xlsx", ".xls"}:
            stat = path.stat()
            info = FileInfo.from_path(path)
            lines = [
                f"📄  {path.name}",
                f"    Type : {info.file_type.value.upper()}",
                f"    Size : {info.size_human}",
                f"    Modified : {info.modified_at:%Y-%m-%d %H:%M:%S}",
                "",
                "This is a binary document.  Use 'process <filename>'",
                "or press Enter on a selected file to extract its text.",
            ]
            return "\n".join(lines)

        # For text files (.txt and others), read content
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n… [{len(text) - max_chars:,} more characters]"
            return text
        except Exception as exc:
            return f"[Cannot read file: {exc}]"

    # ── Single-file processing ───────────────────────────────

    @staticmethod
    def process_file(file_path: str | Path) -> ProcessResult:
        """
        Route a single file through the extraction pipeline and
        save the result to PROCESSED/.

        This is the method the TUI calls when a user selects a file
        and presses Enter or types ``process <filename>``.
        """
        path = Path(file_path)
        start = time.time()

        if not path.exists():
            return ProcessResult(
                source_file=path.name,
                success=False,
                error_message=f"File not found: {path}",
            )

        # Check if already processed
        processed_path = Path(PROCESSED_DIR) / f"{path.stem}.txt"
        if processed_path.exists():
            return ProcessResult(
                source_file=path.name,
                success=True,
                output_path=str(processed_path),
                char_count=len(processed_path.read_text(encoding="utf-8")),
                error_message="Already processed (skipped).",
                duration_seconds=time.time() - start,
            )

        try:
            text = route(str(path))
        except Exception as exc:
            logger.error("Failed to extract '%s': %s", path.name, exc, exc_info=True)
            return ProcessResult(
                source_file=path.name,
                success=False,
                error_message=str(exc),
                duration_seconds=time.time() - start,
            )

        if text is None:
            return ProcessResult(
                source_file=path.name,
                success=False,
                error_message="No text could be extracted (unsupported or empty).",
                duration_seconds=time.time() - start,
            )

        saved = save_text(path, text)
        return ProcessResult(
            source_file=path.name,
            success=True,
            output_path=str(saved),
            char_count=len(text),
            duration_seconds=time.time() - start,
        )

    # ── Batch processing ─────────────────────────────────────

    @classmethod
    def process_all(cls) -> BatchResult:
        """
        Run the full extraction pipeline over every pending file in
        INPUT/.  Already-processed files are skipped automatically.
        """
        cls.ensure_directories()
        start = time.time()

        input_files = cls.list_input_files()
        pending = [f for f in input_files if f.status == FileStatus.PENDING]

        batch = BatchResult(total_files=len(input_files))
        batch.skipped = len(input_files) - len(pending)

        for fi in pending:
            result = cls.process_file(fi.path)
            batch.results.append(result)
            if result.success:
                batch.processed += 1
            else:
                batch.errors += 1

        batch.duration_seconds = time.time() - start
        logger.info(batch.summary)
        return batch

    # ── Configuration ────────────────────────────────────────

    @staticmethod
    def get_config() -> dict[str, str]:
        """Return the current runtime configuration as a flat dict."""
        from config import (
            INPUT_DIR,
            OCR_DPI,
            OCR_LANGUAGES,
            OUTPUT_DIR,
            PDF_TEXT_THRESHOLD,
            PROCESSED_DIR,
        )

        return {
            "INPUT_DIR": INPUT_DIR,
            "PROCESSED_DIR": PROCESSED_DIR,
            "OUTPUT_DIR": OUTPUT_DIR,
            "OCR_LANGUAGES": OCR_LANGUAGES,
            "OCR_DPI": str(OCR_DPI),
            "PDF_TEXT_THRESHOLD": str(PDF_TEXT_THRESHOLD),
            "SUPPORTED_EXTENSIONS": ", ".join(sorted(SUPPORTED_EXTENSIONS)),
        }

    # ── Statistics ────────────────────────────────────────────

    @classmethod
    def get_pipeline_stats(cls) -> PipelineStats:
        """Compute quick dashboard statistics."""
        input_files = cls.list_input_files()
        processed_files = cls.list_processed_files()

        pending = sum(1 for f in input_files if f.status == FileStatus.PENDING)
        input_size = sum(f.size_bytes for f in input_files)
        proc_size = sum(f.size_bytes for f in processed_files)

        def _human(size: int) -> str:
            for unit in ("B", "KB", "MB", "GB"):
                if size < 1024:
                    return f"{size:.1f} {unit}"
                size /= 1024
            return f"{size:.1f} TB"

        return PipelineStats(
            input_file_count=len(input_files),
            processed_file_count=len(processed_files),
            pending_count=pending,
            input_total_size=_human(input_size),
            processed_total_size=_human(proc_size),
        )
