"""Minimal client for the local Ollama HTTP API. There is no fallback to any other model."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


class OllamaError(Exception):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status  # UNAVAILABLE | MODEL_MISSING | TIMEOUT | ERROR
        self.message = message


@dataclass(frozen=True)
class GenerationResult:
    text: str
    latency_ms: float
    model: str


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=timeout, transport=self._transport)

    async def status(self) -> dict:
        started = time.perf_counter()
        try:
            async with self._client(3.0) as client:
                response = await client.get("/api/tags")
            response.raise_for_status()
            models = [m.get("name", "") for m in response.json().get("models", [])]
        except (httpx.HTTPError, ValueError):
            return {
                "status": "UNREACHABLE",
                "model": self.model,
                "model_available": False,
                "available_models": [],
                "latency_ms": _ms(started),
                "message": "Ollama is not running or not reachable at the configured URL.",
            }
        available = self._model_present(models)
        return {
            "status": "CONNECTED" if available else "MODEL_MISSING",
            "model": self.model,
            "model_available": available,
            "available_models": models[:20],
            "latency_ms": _ms(started),
            "message": "Ollama is connected and the configured model is available."
            if available
            else f"Ollama is running but model '{self.model}' is not installed. Run: ollama pull {self.model}",
        }

    def _model_present(self, models: list[str]) -> bool:
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        return self.model in models or wanted in models

    async def generate(self, prompt: str, max_tokens: int = 160) -> GenerationResult:
        started = time.perf_counter()
        body = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": max_tokens},
        }
        try:
            async with self._client(self.timeout_seconds) as client:
                response = await client.post("/api/generate", json=body)
        except httpx.TimeoutException as exc:
            raise OllamaError("TIMEOUT", f"Local model did not respond within {self.timeout_seconds:g} seconds.") from exc
        except httpx.HTTPError as exc:
            raise OllamaError("UNAVAILABLE", "Ollama is not reachable at the configured URL.") from exc

        if response.status_code == 404:
            raise OllamaError("MODEL_MISSING", f"Model '{self.model}' is not installed in Ollama.")
        if response.status_code != 200:
            raise OllamaError("ERROR", f"Ollama returned HTTP {response.status_code}.")
        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaError("ERROR", "Ollama returned a response that is not JSON.") from exc
        text = data.get("response") if isinstance(data, dict) else None
        if not isinstance(text, str):
            raise OllamaError("ERROR", "Ollama response did not contain generated text.")
        return GenerationResult(text=text, latency_ms=_ms(started), model=self.model)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
