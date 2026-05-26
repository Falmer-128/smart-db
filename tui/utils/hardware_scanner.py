"""
Hardware Scanner — async, hardware-aware LLM capability detection.

Queries the host for GPU VRAM via nvidia-smi, computes usable capacity,
matches against a model catalog, tracks hardware changes between sessions
via models_registry.json (stored at project root for USB portability),
and flags VRAM regressions that risk OOM.
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────

# 1.5 GB reserved for OS compositor, display server, and KV-cache headroom
OS_OVERHEAD_MB: int = 1536

# Percentage drop in VRAM that triggers an OOM warning
VRAM_DROP_THRESHOLD: float = 0.20  # 20%

# Project root — two levels up from tui/utils/hardware_scanner.py
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
REGISTRY_PATH: Path = PROJECT_ROOT / "models_registry.json"

# ── Model Catalog ────────────────────────────────────────────
# Ordered by VRAM requirement descending. Each entry represents an
# Ollama-compatible model tag and the minimum VRAM (in MB) required
# to load the full model weights without CPU offloading.

MODEL_CATALOG: list[dict[str, Any]] = [
    {"name": "qwen2.5:72b",  "vram_required_mb": 41_000, "param_label": "72B"},
    {"name": "qwen2.5:32b",  "vram_required_mb": 20_000, "param_label": "32B"},
    {"name": "qwen2.5:14b",  "vram_required_mb": 10_000, "param_label": "14B"},
    {"name": "qwen2.5:7b",   "vram_required_mb": 5_500,  "param_label": "7B"},
    {"name": "qwen2.5:3b",   "vram_required_mb": 2_800,  "param_label": "3B"},
    {"name": "gemma2:2b",    "vram_required_mb": 2_000,  "param_label": "2B"},
    {"name": "qwen2.5:1.5b", "vram_required_mb": 1_500,  "param_label": "1.5B"},
    {"name": "qwen2.5:0.5b", "vram_required_mb": 500,    "param_label": "0.5B"},
]


# ── Data Classes ─────────────────────────────────────────────

@dataclass
class ModelInfo:
    """Describes a single model's compatibility with the current hardware."""
    name: str
    vram_required_mb: int
    param_label: str
    fits: bool
    is_recommended: bool = False


@dataclass
class HardwareSpecs:
    """Complete hardware scan result with model recommendations."""
    os_name: str
    gpu_present: bool
    gpu_name: str = ""
    raw_vram_mb: int = 0
    usable_vram_mb: int = 0
    assigned_tier: int = 3
    available_models: list[ModelInfo] = field(default_factory=list)
    vram_delta_pct: float | None = None
    vram_warning: bool = False


# ── Registry Persistence ─────────────────────────────────────

def _load_registry() -> dict[str, Any]:
    """Load the hardware state registry from project root."""
    if REGISTRY_PATH.exists():
        try:
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read models registry: %s", exc)
    return {}


def _save_registry(raw_vram_mb: int) -> None:
    """Persist the current VRAM reading to the registry."""
    data = {
        "last_raw_vram_mb": raw_vram_mb,
        "last_scan_ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info("Saved hardware registry to %s", REGISTRY_PATH)
    except OSError as exc:
        logger.warning("Failed to write models registry: %s", exc)


# ── VRAM Delta Calculation ───────────────────────────────────

def _compute_vram_delta(
    current_vram_mb: int, registry: dict[str, Any]
) -> tuple[float | None, bool]:
    """
    Compare current VRAM against the last recorded session.

    Returns
    -------
    (delta_pct, warning)
        delta_pct : signed percentage change (negative = drop), or None
                    if no prior session exists.
        warning   : True if the current VRAM is ≥20% lower than last time.
    """
    last_vram = registry.get("last_raw_vram_mb")
    if last_vram is None or last_vram <= 0:
        return None, False

    delta_pct = (current_vram_mb - last_vram) / last_vram
    warning = delta_pct <= -VRAM_DROP_THRESHOLD
    return round(delta_pct * 100, 1), warning


# ── Model Matching ───────────────────────────────────────────

def _match_models(usable_vram_mb: int) -> list[ModelInfo]:
    """
    Iterate the catalog and tag each model as fitting / not fitting.
    The largest model that fits is tagged as `is_recommended`.
    """
    models: list[ModelInfo] = []
    recommended_set = False

    for entry in MODEL_CATALOG:
        fits = entry["vram_required_mb"] <= usable_vram_mb
        is_rec = fits and not recommended_set
        if is_rec:
            recommended_set = True

        models.append(
            ModelInfo(
                name=entry["name"],
                vram_required_mb=entry["vram_required_mb"],
                param_label=entry["param_label"],
                fits=fits,
                is_recommended=is_rec,
            )
        )

    return models


# ── Tier Assignment ──────────────────────────────────────────

def _assign_tier(usable_vram_mb: int) -> int:
    """Map usable VRAM to a human-readable tier number."""
    if usable_vram_mb >= 8192:
        return 1  # High-end (≥8 GB usable)
    elif usable_vram_mb >= 4096:
        return 2  # Mid-range (4–8 GB usable)
    else:
        return 3  # Low / CPU fallback (<4 GB usable)


# ── Main Scanner ─────────────────────────────────────────────

async def get_hardware_specs() -> HardwareSpecs:
    """
    Async hardware scan.

    Queries nvidia-smi via an async subprocess, computes usable VRAM,
    matches models, checks the registry for VRAM regressions, and
    persists the new state.
    """
    os_name = platform.system()
    gpu_present = False
    gpu_name = ""
    raw_vram_mb = 0
    usable_vram_mb = 0

    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=memory.total,memory.free,name",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0 and stdout:
            output = stdout.decode().strip()
            if output:
                # Parse first GPU line: "8192, 7500, NVIDIA GeForce RTX 3070"
                first_gpu = output.split("\n")[0]
                parts = [p.strip() for p in first_gpu.split(",")]
                raw_vram_mb = int(parts[0])
                gpu_name = parts[2] if len(parts) >= 3 else "NVIDIA GPU"
                gpu_present = True
                usable_vram_mb = max(0, raw_vram_mb - OS_OVERHEAD_MB)

    except FileNotFoundError:
        logger.info("nvidia-smi not found — assuming no NVIDIA GPU.")
    except (ValueError, IndexError) as exc:
        logger.warning("Failed to parse nvidia-smi output: %s", exc)
    except OSError as exc:
        logger.warning("OS error querying nvidia-smi: %s", exc)

    # ── Model matching ───────────────────────────────────────
    available_models = _match_models(usable_vram_mb)
    assigned_tier = _assign_tier(usable_vram_mb)

    # ── Registry: detect VRAM regressions ────────────────────
    registry = _load_registry()
    vram_delta_pct, vram_warning = _compute_vram_delta(raw_vram_mb, registry)

    # Persist the new state
    if gpu_present:
        _save_registry(raw_vram_mb)

    return HardwareSpecs(
        os_name=os_name,
        gpu_present=gpu_present,
        gpu_name=gpu_name,
        raw_vram_mb=raw_vram_mb,
        usable_vram_mb=usable_vram_mb,
        assigned_tier=assigned_tier,
        available_models=available_models,
        vram_delta_pct=vram_delta_pct,
        vram_warning=vram_warning,
    )


# ── CLI entry for standalone testing ─────────────────────────

if __name__ == "__main__":
    import asyncio as _aio

    async def _main() -> None:
        specs = await get_hardware_specs()
        print("Detected Hardware Specs:")
        print(f"  OS:            {specs.os_name}")
        print(f"  GPU present:   {specs.gpu_present}")
        print(f"  GPU name:      {specs.gpu_name}")
        print(f"  Raw VRAM:      {specs.raw_vram_mb} MB")
        print(f"  Usable VRAM:   {specs.usable_vram_mb} MB")
        print(f"  Tier:          {specs.assigned_tier}")
        print(f"  VRAM Δ:        {specs.vram_delta_pct}%")
        print(f"  VRAM warning:  {specs.vram_warning}")
        print()
        print("  Available models:")
        for m in specs.available_models:
            badge = " ⭐ RECOMMENDED" if m.is_recommended else ""
            status = "✅ fits" if m.fits else "❌ too large"
            print(f"    {m.name:20s} ({m.vram_required_mb:>6,} MB) {status}{badge}")

    _aio.run(_main())
