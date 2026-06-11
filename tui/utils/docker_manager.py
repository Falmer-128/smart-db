from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncGenerator, Any, Callable

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
                except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
                    pass  # Not up yet — keep polling

                await asyncio.sleep(OLLAMA_POLL_INTERVAL)
                elapsed += OLLAMA_POLL_INTERVAL

        return DockerStatus(False, 
            f"Ollama did not respond within {OLLAMA_STARTUP_TIMEOUT}s. "
            "Check `docker compose logs ollama` for details."
        )



def generate_env_file(state: Any, filepath: str = ".env") -> None:
    """
    Generate the .env file for docker-compose based on the App state.

    Reads the existing .env file to preserve internal variables (like AnythingLLM's SIG_KEY),
    then updates/appends the core LLM settings and external provider API keys.
    """
    env_vars = {}
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        k, v = line.split("=", 1)
                        env_vars[k.strip()] = v.strip()

    # Core Settings
    env_vars["STORAGE_DIR"] = "/app/server/storage"
    
    # LLM routing
    provider = getattr(state, "llm_provider", getattr(state, "backend", "ollama"))
    env_vars["LLM_PROVIDER"] = provider
    env_vars["LLM_MODEL"] = getattr(state, "model_name", "")
    env_vars["LLM_BACKEND"] = provider
    env_vars["GPU_TIER"] = getattr(state, "assigned_tier", "")

    # External provider API keys
    api_key = getattr(state, "api_key", "")
    ext_model = getattr(state, "external_model", "")

    if provider == "openrouter":
        if api_key: env_vars["OPENROUTER_API_KEY"] = api_key
        if ext_model: env_vars["OPENROUTER_MODEL"] = ext_model
    elif provider == "nvidia_nim":
        if api_key: env_vars["NVIDIA_NIM_API_KEY"] = api_key
        if ext_model: env_vars["NVIDIA_NIM_MODEL"] = ext_model
    elif provider == "google_gemini":
        if api_key: env_vars["GEMINI_API_KEY"] = api_key
        if ext_model: env_vars["GEMINI_MODEL"] = ext_model

    # Downloaded models list
    downloaded = getattr(state, "downloaded_models", [])
    if downloaded:
        env_vars["DOWNLOADED_MODELS"] = ",".join(downloaded)

    # Vision provider settings
    env_vars["VISION_PROVIDER"] = getattr(state, "vision_provider", "google")
    
    vision_key = getattr(state, "vision_api_key", "")
    if vision_key:
        env_vars["VISION_API_KEY"] = vision_key
        
    vision_model = getattr(state, "vision_model", "")
    if vision_model:
        env_vars["VISION_MODEL"] = vision_model

    # Write back to .env
    lines = ["# Auto-generated and merged by smart-db Setup Wizard"]
    for k, v in env_vars.items():
        # Ensure values aren't explicitly single-quoted for Docker Compose
        val_str = str(v)
        if val_str.startswith("'") and val_str.endswith("'"):
            val_str = val_str[1:-1]
        lines.append(f"{k}={val_str}")
        
    lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


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
