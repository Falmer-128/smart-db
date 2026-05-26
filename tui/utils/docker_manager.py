from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncGenerator, Any, Callable

import httpx

logger = logging.getLogger(__name__)

OLLAMA_HEALTH_URL = "http://localhost:11434/"
OLLAMA_STARTUP_TIMEOUT = 30  # seconds
OLLAMA_POLL_INTERVAL = 1.0   # seconds


async def ensure_ollama_running(
    cwd: str | None = None,
    log_callback: Callable[[str], None] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> tuple[bool, str]:
    """
    Lazily start the Ollama container and wait until its API is healthy.

    1. Runs ``docker compose up -d ollama`` (async, non-blocking).
    2. Polls ``GET http://localhost:11434/`` every second until it
       returns HTTP 200 or the timeout (30 s) expires.

    Parameters
    ----------
    cwd : str | None
        Working directory containing ``docker-compose.yml``.
        Defaults to the current working directory.
    log_callback : Callable[[str], None] | None
        Optional callback to stream output (e.g. from docker pull).
    cancel_event : asyncio.Event | None
        Optional event to signal cancellation during the docker pull process.

    Returns
    -------
    (success, message)
        ``success`` is True when the Ollama API is confirmed alive.
    """
    if cwd is None:
        cwd = os.getcwd()

    # ── Check if image exists ────────────────────────────────
    check_proc = await asyncio.create_subprocess_exec(
        "docker", "images", "-q", "ollama/ollama",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await check_proc.communicate()
    image_exists = bool(stdout.strip())

    if not image_exists:
        max_attempts = 5
        pull_success = False

        for attempt in range(1, max_attempts + 1):
            if attempt == 1:
                if log_callback:
                    log_callback("Pulling ollama/ollama base image...\n")
            else:
                if log_callback:
                    log_callback(f"⚠️ Connection stalled. Reconnecting and resuming download (Attempt {attempt}/{max_attempts})...\n")

            pull_proc = await asyncio.create_subprocess_exec(
                "docker", "pull", "ollama/ollama",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )

            if pull_proc.stdout:
                while True:
                    try:
                        if cancel_event:
                            read_task = asyncio.create_task(pull_proc.stdout.readline())
                            cancel_task = asyncio.create_task(cancel_event.wait())
                            done, pending = await asyncio.wait(
                                [read_task, cancel_task],
                                timeout=45.0,
                                return_when=asyncio.FIRST_COMPLETED
                            )
                            
                            if not done:
                                pull_proc.kill()
                                for p in pending:
                                    p.cancel()
                                break
                            
                            if cancel_task in done:
                                pull_proc.kill()
                                for p in pending:
                                    p.cancel()
                                return False, "Cancelled by user"
                            
                            line = read_task.result()
                            for p in pending:
                                p.cancel()
                        else:
                            line = await asyncio.wait_for(
                                pull_proc.stdout.readline(), timeout=45.0
                            )
                    except asyncio.TimeoutError:
                        pull_proc.kill()
                        break
                    
                    if not line:
                        break
                    
                    if log_callback:
                        log_callback(line.decode(errors='replace'))
            
            await pull_proc.wait()
            if pull_proc.returncode == 0:
                pull_success = True
                break
        
        if not pull_success:
            return False, f"Failed to pull ollama/ollama image after {max_attempts} attempts."

    # ── Step 1: Start the container ──────────────────────────
    proc = await asyncio.create_subprocess_shell(
        "docker compose up -d ollama 2>&1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode().strip() if stdout else ""

    if proc.returncode != 0:
        return False, f"docker compose failed (exit {proc.returncode}): {output}"

    # ── Step 2: Poll until the API is alive ──────────────────
    elapsed = 0.0
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        while elapsed < OLLAMA_STARTUP_TIMEOUT:
            try:
                resp = await client.get(OLLAMA_HEALTH_URL)
                if resp.status_code == 200:
                    return True, "Ollama is ready."
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
                pass  # Not up yet — keep polling

            await asyncio.sleep(OLLAMA_POLL_INTERVAL)
            elapsed += OLLAMA_POLL_INTERVAL

    return False, (
        f"Ollama did not respond within {OLLAMA_STARTUP_TIMEOUT}s. "
        "Check `docker compose logs ollama` for details."
    )



def generate_env_file(state: Any, filepath: str = ".env") -> None:
    """
    Generate the .env file for docker-compose based on the App state.

    Writes core LLM settings plus any external provider API keys.
    """
    lines = [
        "# Auto-generated by smart-db Setup Wizard",
        f"LLM_MODEL={state.model_name}",
        f"LLM_BACKEND={getattr(state, 'llm_provider', state.backend)}",
        f"GPU_TIER={state.assigned_tier}",
    ]

    # External provider API keys
    provider = getattr(state, "llm_provider", "ollama")

    if provider == "openrouter":
        api_key = getattr(state, "api_key", "")
        if api_key:
            lines.append(f"OPENROUTER_API_KEY={api_key}")
        ext_model = getattr(state, "external_model", "")
        if ext_model:
            lines.append(f"OPENROUTER_MODEL={ext_model}")

    elif provider == "nvidia_nim":
        api_key = getattr(state, "api_key", "")
        if api_key:
            lines.append(f"NVIDIA_NIM_API_KEY={api_key}")
        ext_model = getattr(state, "external_model", "")
        if ext_model:
            lines.append(f"NVIDIA_NIM_MODEL={ext_model}")

    # Downloaded models list (for reference)
    downloaded = getattr(state, "downloaded_models", [])
    if downloaded:
        lines.append(f"DOWNLOADED_MODELS={','.join(downloaded)}")

    lines.append("")  # Trailing newline

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


async def run_docker_compose_up(cwd: str = ".") -> AsyncGenerator[str, None]:
    """
    Runs docker compose up -d --build and yields combined stdout/stderr lines.
    2>&1 redirects stderr to stdout so we can stream it all sequentially.
    """
    process = await asyncio.create_subprocess_shell(
        "docker compose up -d --build 2>&1",
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
