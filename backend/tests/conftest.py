"""Shared fixtures.

Detection uses the real Presidio engine (loaded once per session). Ollama is replaced by an
httpx MockTransport, and the mock CloudLink receiver runs in-process behind an ASGI
transport that counts every request that reaches it. No credentials or network access
are required.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import base64

import httpx
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import Container, build_analyzer, build_container
from app.integrations.mock_cloudlink import create_mock_cloudlink_app
from app.main import create_app

DEMO_TRANSCRIPT = "My name is John Smith, my patient ID is 48291, and I need help with my appointment."
TEST_KEY = "test-cloudlink-key"
VAULT_KEY = Fernet.generate_key().decode("ascii")
SIGNING_KEY = base64.b64encode(
    Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
).decode("ascii")


@pytest.fixture(scope="session")
def analyzer():
    a = build_analyzer(Settings())
    a.load()
    assert a.ready, a.message
    return a


def fixed_embedding(text: str) -> list[float]:
    """Deterministic stand-in for an embedding model: a few simple text features."""
    return [float(len(text)), float(sum(c.isupper() for c in text)), float(text.count(" ")), 1.0]


@dataclass
class OllamaStub:
    """Behaviour: ok | missing | timeout | down | empty | echo | fixed."""

    mode: str = "ok"
    fixed_text: str = "Customer requested assistance with an appointment."
    prompts: list[str] = field(default_factory=list)
    embed_missing: bool = False  # the embedding model is not pulled
    embedded: list[str] = field(default_factory=list)
    delay_s: float = 0.0  # simulated generation time, for benchmark tests

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.mode == "down":
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path == "/api/tags":
            models = [] if self.mode == "missing" else [{"name": "llama3.2:3b"}]
            if not self.embed_missing:
                models.append({"name": "nomic-embed-text:latest"})
            return httpx.Response(200, json={"models": models})
        if request.url.path == "/api/embed":
            if self.embed_missing:
                return httpx.Response(404, json={"error": 'model "nomic-embed-text" not found, try pulling it first'})
            texts = json.loads(request.content)["input"]
            self.embedded.extend(texts)
            return httpx.Response(200, json={"embeddings": [fixed_embedding(t) for t in texts]})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.0.0-stub"})
        if request.url.path == "/api/generate":
            prompt = json.loads(request.content)["prompt"]
            self.prompts.append(prompt)
            if self.delay_s:
                time.sleep(self.delay_s)
            if self.mode == "timeout":
                raise httpx.ReadTimeout("timed out", request=request)
            if self.mode == "missing":
                return httpx.Response(404, json={"error": "model 'llama3.2:3b' not found"})
            if self.mode == "empty":
                return httpx.Response(200, json={"response": "   "})
            if self.mode == "echo_tokens":
                # Echo every token from the prompt, like a model that keeps the tokens.
                tokens = sorted(set(re.findall(r"\[[A-Z][A-Z_]*_\d+\]", prompt.split("Transcript:", 1)[-1])))
                return httpx.Response(200, json={"response": "- Caller " + " ".join(tokens) + " needs help.", "done": True})
            return httpx.Response(200, json={"response": self.fixed_text, "done": True})
        return httpx.Response(404)


class CountingTransport(httpx.AsyncBaseTransport):
    """Wraps the receiver ASGI app and records every request that reaches it."""

    def __init__(self, app, fail: bool = False) -> None:
        self._inner = httpx.ASGITransport(app=app)
        self.requests: list[httpx.Request] = []
        self.fail = fail

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            raise httpx.ConnectError("receiver down", request=request)
        self.requests.append(request)
        return await self._inner.handle_async_request(request)

    def handoff_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == "/v1/handoff"]


@dataclass
class Harness:
    client: TestClient
    container: Container
    ollama: OllamaStub
    receiver_transport: CountingTransport
    receiver_app: object
    db_path: Path

    def process(self, transcript: str = DEMO_TRANSCRIPT, profile: str = "standard", mode: str = "full", **extra):
        return self.client.post("/api/process", json={"transcript": transcript, "profile": profile, "mode": mode, **extra})


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "database_url": f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        "cloudlink_api_key": TEST_KEY,
        "cloudlink_base_url": "http://mock-cloudlink",
        "ollama_base_url": "http://mock-ollama",
        "ollama_model": "llama3.2:3b",
        "admin_api_key": "",
        "vault_key": VAULT_KEY,
        "receipt_signing_key": SIGNING_KEY,
        "keys_dir": tmp_path / "keys",
        "received_log_file": tmp_path / "received.log",
        "mock_cloud_model": "",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def harness_factory(tmp_path, analyzer):
    opened: list[TestClient] = []

    def factory(ollama_mode: str = "ok", receiver_down: bool = False, **overrides) -> Harness:
        settings = make_settings(tmp_path, **overrides)
        stub = OllamaStub(mode=ollama_mode)
        receiver_app = create_mock_cloudlink_app(settings, ollama_transport=httpx.MockTransport(stub.handler))
        transport = CountingTransport(receiver_app, fail=receiver_down)
        container = build_container(
            settings,
            analyzer=analyzer,
            ollama_transport=httpx.MockTransport(stub.handler),
            cloudlink_transport=transport,
        )
        client = TestClient(create_app(settings, container))
        client.__enter__()
        opened.append(client)
        return Harness(client, container, stub, transport, receiver_app, tmp_path / "test.db")

    yield factory
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def harness(harness_factory) -> Harness:
    return harness_factory()
