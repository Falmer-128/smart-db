"""
LLM Router — async, provider-agnostic query routing for Local Ollama,
OpenRouter, and NVIDIA NIM backends.

Usage:
    router = await LLMRouter.from_env()
    response = await router.query("Summarize this document.")
    await router.close()
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env from the project root
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")


# ── Provider Enum ────────────────────────────────────────────

class LLMProvider(str, Enum):
    """Supported LLM inference backends."""
    LOCAL_OLLAMA = "ollama"
    OPENROUTER = "openrouter"
    NVIDIA_NIM = "nvidia_nim"


# ── Provider Endpoint Configuration ──────────────────────────

PROVIDER_ENDPOINTS: dict[LLMProvider, str] = {
    LLMProvider.LOCAL_OLLAMA: "http://localhost:11434",
    LLMProvider.OPENROUTER: "https://openrouter.ai/api/v1",
    LLMProvider.NVIDIA_NIM: "https://integrate.api.nvidia.com/v1",
}

PROVIDER_DEFAULT_MODELS: dict[LLMProvider, str] = {
    LLMProvider.LOCAL_OLLAMA: "qwen2.5:7b",
    LLMProvider.OPENROUTER: "meta-llama/llama-3.1-8b-instruct",
    LLMProvider.NVIDIA_NIM: "meta/llama-3.1-8b-instruct",
}


# ── Configuration ────────────────────────────────────────────

@dataclass
class LLMRouterConfig:
    """Configuration for the LLM Router."""
    provider: LLMProvider
    model_name: str
    api_key: str = ""
    base_url: str = ""
    timeout: float = 120.0

    def __post_init__(self) -> None:
        if not self.base_url:
            self.base_url = PROVIDER_ENDPOINTS[self.provider]
        if not self.model_name:
            self.model_name = PROVIDER_DEFAULT_MODELS[self.provider]


# ── Router ───────────────────────────────────────────────────

class LLMRouter:
    """
    Async LLM query router.

    Dynamically directs queries to Local Ollama, OpenRouter, or
    NVIDIA NIM based on the configured provider. Manages HTTP
    client lifecycle and auth header injection.
    """

    def __init__(self, config: LLMRouterConfig) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None

    # ── Lifecycle ────────────────────────────────────────────

    def _ensure_client(self) -> httpx.AsyncClient:
        """Lazily create the httpx client with provider-appropriate headers."""
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {
                "Content-Type": "application/json",
            }

            if self.config.provider == LLMProvider.OPENROUTER:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
                headers["HTTP-Referer"] = "https://github.com/smart-db"
                headers["X-Title"] = "smart-db"
            elif self.config.provider == LLMProvider.NVIDIA_NIM:
                headers["Authorization"] = f"Bearer {self.config.api_key}"

            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers=headers,
                timeout=httpx.Timeout(self.config.timeout),
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── Query (non-streaming) ────────────────────────────────

    async def query(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> str:
        """
        Send a prompt and return the full response text.

        Routes to the appropriate API based on the configured provider.
        """
        client = self._ensure_client()

        if self.config.provider == LLMProvider.LOCAL_OLLAMA:
            return await self._query_ollama(
                client, prompt, system, temperature, **kwargs
            )
        else:
            return await self._query_openai_compat(
                client, prompt, system, temperature, max_tokens, **kwargs
            )

    async def _query_ollama(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        system: str,
        temperature: float,
        **kwargs: Any,
    ) -> str:
        """Query local Ollama /api/generate endpoint."""
        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system

        resp = await client.post("/api/generate", json=payload)
        resp.raise_for_status()
        return resp.json().get("response", "")

    async def _query_openai_compat(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> str:
        """Query OpenAI-compatible endpoints (OpenRouter, NVIDIA NIM)."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = await client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    # ── Stream ───────────────────────────────────────────────

    async def stream(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """
        Stream response tokens as they arrive.

        Yields individual text chunks suitable for real-time display.
        """
        client = self._ensure_client()

        if self.config.provider == LLMProvider.LOCAL_OLLAMA:
            async for chunk in self._stream_ollama(
                client, prompt, system, temperature, **kwargs
            ):
                yield chunk
        else:
            async for chunk in self._stream_openai_compat(
                client, prompt, system, temperature, max_tokens, **kwargs
            ):
                yield chunk

    async def _stream_ollama(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        system: str,
        temperature: float,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Stream from Ollama /api/generate."""
        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system

        async with client.stream("POST", "/api/generate", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    token = data.get("response", "")
                    if token:
                        yield token
                    if data.get("done", False):
                        return
                except json.JSONDecodeError:
                    continue

    async def _stream_openai_compat(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Stream from OpenAI-compatible SSE endpoints."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        async with client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]  # Strip "data: " prefix
                if data_str.strip() == "[DONE]":
                    return
                try:
                    data = json.loads(data_str)
                    delta = data["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    # ── Connection Test ──────────────────────────────────────

    async def test_connection(self) -> tuple[bool, str]:
        """
        Verify connectivity to the configured provider.

        Returns (success: bool, message: str).
        """
        try:
            client = self._ensure_client()

            if self.config.provider == LLMProvider.LOCAL_OLLAMA:
                resp = await client.get("/api/tags")
                resp.raise_for_status()
                models = resp.json().get("models", [])
                return True, f"Connected. {len(models)} model(s) available."

            else:
                # For cloud providers, send a minimal request
                resp = await self.query("Hi", max_tokens=5)
                return True, "Connection successful."

        except httpx.ConnectError:
            return False, "Connection refused. Is the service running?"
        except httpx.HTTPStatusError as exc:
            return False, f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        except Exception as exc:
            return False, f"Error: {exc}"

    # ── Factory ──────────────────────────────────────────────

    @classmethod
    async def from_env(cls) -> "LLMRouter":
        """
        Factory: build an LLMRouter from environment variables.

        Reads:
            LLM_BACKEND       – "ollama" | "openrouter" | "nvidia_nim"
            LLM_MODEL          – model name/tag
            OPENROUTER_API_KEY – API key for OpenRouter
            NVIDIA_NIM_API_KEY – API key for NVIDIA NIM
        """
        backend = os.getenv("LLM_BACKEND", "ollama").lower().strip()

        try:
            provider = LLMProvider(backend)
        except ValueError:
            logger.warning("Unknown LLM_BACKEND '%s', falling back to ollama", backend)
            provider = LLMProvider.LOCAL_OLLAMA

        model = os.getenv("LLM_MODEL", PROVIDER_DEFAULT_MODELS[provider])

        api_key = ""
        if provider == LLMProvider.OPENROUTER:
            api_key = os.getenv("OPENROUTER_API_KEY", "")
        elif provider == LLMProvider.NVIDIA_NIM:
            api_key = os.getenv("NVIDIA_NIM_API_KEY", "")

        config = LLMRouterConfig(
            provider=provider,
            model_name=model,
            api_key=api_key,
        )

        return cls(config)
