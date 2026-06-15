from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncGenerator, Any, Callable
from pathlib import Path

from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

OLLAMA_HEALTH_URL = "http://localhost:11434/"
OLLAMA_STARTUP_TIMEOUT = 30  # seconds
OLLAMA_POLL_INTERVAL = 1.0   # seconds


@dataclass
class DockerStatus:
    success: bool
    message: str


class DockerManager:
    def __init__(self):
        self._cancel_event = asyncio.Event()

    def abort_all(self):
        """Trigger cancellation for any running operations."""
        self._cancel_event.set()

    def reset_cancellation(self):
        """Reset the cancellation event for a new operation."""
        self._cancel_event.clear()

    async def ensure_ollama_running(
        self,
        cwd: str | None = None,
        log_callback: Callable[[str], None] | None = None,
    ) -> DockerStatus:
        """
        Lazily start the Ollama container and wait until its API is healthy.

        1. Runs ``docker compose up -d ollama`` (async, non-blocking).
        2. Polls ``GET http://localhost:11434/`` every second until it
           returns HTTP 200 or the timeout (30 s) expires.
        """
        if cwd is None:
            cwd = os.getcwd()

        self.reset_cancellation()

        # ── Check if image exists ────────────────────────────────
        check_proc = await asyncio.create_subprocess_exec(
            "docker", "images", "-q", "ollama/ollama",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await check_proc.communicate()
        image_exists = bool(stdout.strip())

        if not image_exists:
            if log_callback:
                log_callback("Pulling ollama/ollama base image...\n")

            pull_proc = await asyncio.create_subprocess_exec(
                "docker", "pull", "ollama/ollama",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )

            if pull_proc.stdout:
                while True:
                    read_task = asyncio.create_task(pull_proc.stdout.readline())
                    cancel_task = asyncio.create_task(self._cancel_event.wait())
                    done, pending = await asyncio.wait(
                        [read_task, cancel_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    if cancel_task in done:
                        # Skip pressed: send SIGTERM (signal 15) so the
                        # Docker daemon can gracefully clean up its cache
                        # and avoid deadlocks / corrupted containerd snapshots.
                        for p in pending:
                            p.cancel()
                        pull_proc.terminate()       # SIGTERM — NOT .kill() (SIGKILL)
                        await pull_proc.wait()       # wait for graceful exit
                        return DockerStatus(False, "Cancelled by user")
                    
                    line = read_task.result()
                    for p in pending:
                        p.cancel()
                    
                    if not line:
                        break
                    
                    if log_callback:
                        log_callback(line.decode(errors='replace'))
            
            await pull_proc.wait()
            if pull_proc.returncode != 0:
                return DockerStatus(False, "Failed to pull ollama/ollama image.")

        # ── Step 1: Start the container ──────────────────────────
        proc = await asyncio.create_subprocess_shell(
            "docker compose --profile local_backend up -d ollama 2>&1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode().strip() if stdout else ""

        if proc.returncode != 0:
            return DockerStatus(False, f"docker compose failed (exit {proc.returncode}): {output}")

        # ── Step 2: Poll until the API is alive ──────────────────
        elapsed = 0.0
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            while elapsed < OLLAMA_STARTUP_TIMEOUT:
                if self._cancel_event.is_set():
                    return DockerStatus(False, "Cancelled by user")
                
                try:
                    resp = await client.get(OLLAMA_HEALTH_URL)
                    if resp.status_code == 200:
                        return DockerStatus(True, "Ollama is ready.")
                except httpx.RequestError:
                    pass  # Not up yet — keep polling

                await asyncio.sleep(OLLAMA_POLL_INTERVAL)
                elapsed += OLLAMA_POLL_INTERVAL

        return DockerStatus(False, 
            f"Ollama did not respond within {OLLAMA_STARTUP_TIMEOUT}s. "
            "Check `docker compose logs ollama` for details."
        )

    async def pull_model(
        self, model_name: str = "bge-m3", log_callback: Callable[[str], None] | None = None
    ) -> DockerStatus:
        self.reset_cancellation()
        
        async with httpx.AsyncClient() as client:
            try:
                if log_callback:
                    log_callback(f"Pulling model {model_name} from Ollama API...\n")
                
                async with client.stream(
                    "POST", "http://localhost:11434/api/pull", json={"name": model_name}, timeout=None
                ) as response:
                    if response.status_code != 200:
                        return DockerStatus(False, f"HTTP {response.status_code}")
                    
                    async for line in response.aiter_lines():
                        if self._cancel_event.is_set():
                            return DockerStatus(False, "Cancelled by user")
                        if not line:
                            continue
                            
                        import json
                        try:
                            data = json.loads(line)
                            status = data.get("status", "")
                            if "total" in data and "completed" in data:
                                total = data["total"]
                                completed = data["completed"]
                                if total > 0:
                                    percent = (completed / total) * 100
                                    if log_callback:
                                        log_callback(f"⏳ {status}: {percent:.1f}%\n")
                            else:
                                if log_callback:
                                    log_callback(f"{status}\n")
                        except json.JSONDecodeError:
                            pass
                return DockerStatus(True, f"Model {model_name} pulled successfully.")
            except Exception as e:
                return DockerStatus(False, f"Failed to pull model: {e}")



def generate_env_file(state: Any, filepath: str = ".env") -> None:
    """
    Generate the .env file for docker-compose based on the App state.

    Writes ONLY infrastructure and host-pipeline routing variables.
    AnythingLLM-specific LLM/Embedding preferences (LLM_PROVIDER,
    GEMINI_API_KEY, EMBEDDING_ENGINE, etc.) are deliberately excluded —
    those are managed by the user via the AnythingLLM Web UI and stored
    in its internal SQLite database.
    """
    import secrets

    # ── Read existing .env to preserve generated secrets ──────────
    existing = {}
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        k, v = line.split("=", 1)
                        existing[k.strip()] = v.strip()

    # ── Infrastructure (immutable) ────────────────────────────────
    env_vars: dict[str, str] = {}
    env_vars["SYSTEM_MODE"] = existing.get("SYSTEM_MODE", "PIPELINE")
    env_vars["OLLAMA_BASE_PATH"] = "http://ollama:11434"
    env_vars["STORAGE_DIR"] = "/app/server/storage"
    env_vars["GPU_TIER"] = str(getattr(state, "assigned_tier", existing.get("GPU_TIER", "")))
    env_vars["ANYTHINGLLM_API_KEY"] = existing.get("ANYTHINGLLM_API_KEY", "")
    env_vars["SIG_KEY"] = existing.get("SIG_KEY", secrets.token_hex(32))
    env_vars["SIG_SALT"] = existing.get("SIG_SALT", secrets.token_hex(32))

    # ── Host pipeline routing (consumed by llm_router.py) ─────────
    provider = getattr(state, "llm_provider", getattr(state, "backend", "ollama"))
    env_vars["LLM_BACKEND"] = provider
    env_vars["LLM_MODEL"] = getattr(state, "model_name", "gemma-4-31b-it")

    # ── LLM API keys (consumed by host-side llm_router.py) ────────
    api_key = getattr(state, "api_key", "")
    if provider == "google_gemini" and api_key:
        env_vars["GEMINI_API_KEY"] = api_key
    elif provider == "openrouter" and api_key:
        env_vars["OPENROUTER_API_KEY"] = api_key
    elif provider == "nvidia_nim" and api_key:
        env_vars["NVIDIA_NIM_API_KEY"] = api_key

    # ── Vision settings (consumed by text_processor.py) ───────────
    env_vars["VISION_PROVIDER"] = getattr(state, "vision_provider", "google")

    vision_key = getattr(state, "vision_api_key", "")
    env_vars["VISION_API_KEY"] = vision_key if vision_key else ""

    vision_model = getattr(state, "vision_model", "")
    env_vars["VISION_MODEL"] = vision_model if vision_model else ""

    # ── Write back to .env ────────────────────────────────────────
    lines = ["# Infrastructure — managed by smart-db Setup Wizard"]
    for k, v in env_vars.items():
        val_str = str(v)
        if val_str.startswith("'") and val_str.endswith("'"):
            val_str = val_str[1:-1]
        lines.append(f"{k}={val_str}")

    lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # Initialize an isolated env file for AnythingLLM to persist Web UI settings safely
    sandbox_env = Path(".env.anythingllm")
    if not sandbox_env.exists():
        sandbox_env.touch()


async def run_docker_compose_up(
    cwd: str = ".",
    services: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Runs docker compose up -d --build and yields combined stdout/stderr lines.

    Parameters
    ----------
    cwd : str
        Working directory containing docker-compose.yml.
    services : list[str] | None
        Explicit list of services to start. When *None*, every service
        defined in the compose file is started (default Docker behaviour).
    """
    cmd = "docker compose --profile local_backend up -d --build"
    if services:
        cmd += " " + " ".join(services)
    cmd += " 2>&1"

    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        cwd=cwd,
    )

    if process.stdout:
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            yield line.decode().rstrip()

    await process.wait()

    if process.returncode != 0:
        raise RuntimeError(
            f"docker compose failed with exit code {process.returncode}"
        )
