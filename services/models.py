"""
Typed data models for the service layer.

These dataclasses define the API contract between the service layer
and any consumer (TUI today, Web UI tomorrow).  They are intentionally
decoupled from internal implementation details of the core pipeline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class FileStatus(Enum):
    """Processing state of a document."""

    PENDING = "pending"
    PROCESSED = "processed"
    ERROR = "error"
    UNSUPPORTED = "unsupported"


class FileType(Enum):
    """Recognised document types."""

    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    XLS = "xls"
    TXT = "txt"
    UNKNOWN = "unknown"

    @classmethod
    def from_extension(cls, ext: str) -> FileType:
        """Map a file extension (with or without leading dot) to a FileType."""
        ext = ext.lstrip(".").lower()
        try:
            return cls(ext)
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True)
class FileInfo:
    """Metadata about a single file in INPUT/ or PROCESSED/."""

    name: str
    path: Path
    size_bytes: int
    modified_at: datetime
    file_type: FileType
    status: FileStatus = FileStatus.PENDING

    @property
    def size_human(self) -> str:
        """Human-readable file size (e.g. '1.2 MB')."""
        size = self.size_bytes
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @classmethod
    def from_path(cls, path: Path, status: FileStatus = FileStatus.PENDING) -> FileInfo:
        """Construct a FileInfo from a filesystem Path."""
        stat = path.stat()
        return cls(
            name=path.name,
            path=path,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime),
            file_type=FileType.from_extension(path.suffix),
            status=status,
        )


@dataclass
class ProcessResult:
    """Outcome of processing a single file."""

    source_file: str
    success: bool
    output_path: str | None = None
    char_count: int = 0
    error_message: str | None = None
    duration_seconds: float = 0.0


@dataclass
class BatchResult:
    """Aggregate outcome of a batch pipeline run."""

    total_files: int = 0
    processed: int = 0
    skipped: int = 0
    errors: int = 0
    results: list[ProcessResult] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def summary(self) -> str:
        """One-line summary for the status bar."""
        return (
            f"Batch complete: {self.processed} processed, "
            f"{self.skipped} skipped, {self.errors} errors "
            f"({self.duration_seconds:.1f}s)"
        )


@dataclass(frozen=True)
class PipelineStats:
    """Quick dashboard statistics."""

    input_file_count: int
    processed_file_count: int
    pending_count: int
    input_total_size: str
    processed_total_size: str
