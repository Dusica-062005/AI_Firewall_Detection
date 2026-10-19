from __future__ import annotations

import asyncio

import httpx

from app.ai.ollama_client import OllamaClient
from app.ai.summarizer import Summarizer
from tests.conftest import OllamaStub


def summarizer(mode: str, **stub_kwargs) -> tuple[Summarizer, OllamaStub]:
    stub = OllamaStub(mode=mode, **stub_kwargs)
    client = OllamaClient("http://mock-ollama", "llama3.2:3b", 1.0, httpx.MockTransport(stub.handler))
    return Summarizer(client), stub


def run(coro):
    return asyncio.run(coro)


def test_successful_summary():
    s, stub = summarizer("ok")
    result = run(s.summarize("My name is [PERSON]."))
    assert result.status == "GENERATED"
    assert result.text == "Customer requested assistance with an appointment."
    assert "[PERSON]" in stub.prompts[0]


def test_missing_model_is_reported_honestly():
    s, _ = summarizer("missing")
    result = run(s.summarize("text"))
    assert result.status == "MODEL_MISSING"
    assert result.text is None


def test_timeout_is_reported():
    s, _ = summarizer("timeout")
    result = run(s.summarize("text"))
    assert result.status == "TIMEOUT"
    assert result.text is None


def test_unreachable_is_reported():
    s, _ = summarizer("down")
    result = run(s.summarize("text"))
    assert result.status == "UNAVAILABLE" and result.text is None


def test_empty_output_is_invalid():
    s, _ = summarizer("empty")
    result = run(s.summarize("text"))
    assert result.status == "INVALID_OUTPUT" and result.text is None


def test_oversized_output_is_invalid():
    s, _ = summarizer("fixed", fixed_text="x" * 5000)
    result = run(s.summarize("text"))
    assert result.status == "INVALID_OUTPUT"


def test_status_reports_missing_model():
    stub = OllamaStub(mode="missing")
    client = OllamaClient("http://mock-ollama", "llama3.2:3b", 1.0, httpx.MockTransport(stub.handler))
    status = run(client.status())
    assert status["status"] == "MODEL_MISSING" and not status["model_available"]
    assert "ollama pull llama3.2:3b" in status["message"]
