"""Application configuration loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = Path(__file__).resolve().parent

APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:4200"

    database_url: str = f"sqlite:///{(BACKEND_ROOT / 'data' / 'firewall.db').as_posix()}"
    audit_retention_days: int = Field(default=30, ge=1, le=3650)

    max_transcript_chars: int = Field(default=10000, ge=100, le=100000)
    max_request_bytes: int = Field(default=65536, ge=1024, le=1048576)

    spacy_model: str = "en_core_web_md"
    detection_score_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    detection_low_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    expose_detected_values: bool = True
    unmatched_entity_action: Literal["LOCAL_ONLY", "BLOCK"] = "LOCAL_ONLY"
    # Detect spoken and split identifiers ("P four eight two", "P48. ... 2913") (FR-15).
    normalize_numbers: bool = True

    policy_seed_file: Path = APP_ROOT / "policies" / "default.yaml"
    detection_config_file: Path = APP_ROOT / "policies" / "detection.yaml"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_timeout_seconds: float = Field(default=45.0, gt=0, le=600)

    cloudlink_base_url: str = "http://localhost:8100"
    cloudlink_timeout_seconds: float = Field(default=5.0, gt=0, le=600)
    cloudlink_api_key: SecretStr = SecretStr("")

    # "Cloud" stand-in: the mock CloudLink receiver summarizes the tokenized transcript with a
    # larger local model. Empty disables cloud summaries (the receiver only acknowledges).
    mock_cloud_model: str = ""
    mock_cloud_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    # Every payload the mock receiver accepts is appended here (JSON lines). Leak canaries
    # measure real leaks against this file, i.e. at the receiving end.
    received_log_file: Path = BACKEND_ROOT / "data" / "received.log"

    # Local transcription (FR-1): faster-whisper on CTranslate2. Audio uploads have their own size
    # limit; every other request keeps MAX_REQUEST_BYTES.
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    max_audio_seconds: int = Field(default=300, ge=5, le=3600)
    max_audio_bytes: int = Field(default=25 * 1024 * 1024, ge=1024, le=200 * 1024 * 1024)
    audio_temp_dir: Path | None = None  # None: the system temp folder; files are deleted after use
    bleep_style: Literal["tone", "silence"] = "tone"  # audio bleeping (FR-16): 1 kHz tone or silence

    # Latency benchmark (NFR-2) and sizing (Feature 7). "Real-time capable" means the warm p95 total
    # at concurrency 1 fits LIVE_ASSIST_BUDGET_S; otherwise the honest claim is post-call wrap-up.
    live_assist_budget_s: float = Field(default=5.0, gt=0, le=600)
    post_call_budget_s: float = Field(default=60.0, gt=0, le=3600)
    benchmark_audio_dir: Path = BACKEND_ROOT / "tests" / "fixtures" / "audio"

    # Breach Report Generator (Feature 8): draft a report automatically when monitoring detects an
    # exposure (a canary run with leaks, or a receipt showing a protected value left). Drafts only.
    auto_draft_breach_reports: bool = True

    # Dial quality score (Feature 4): Ollama embedding model, and the model that summarizes the
    # RAW synthetic samples as the reference. Empty -> MOCK_CLOUD_MODEL if set, else OLLAMA_MODEL.
    quality_embed_model: str = "nomic-embed-text"
    quality_reference_model: str = ""

    # Trust layer secrets. Generate both with: python scripts/generate_keys.py
    vault_key: SecretStr = SecretStr("")  # Fernet key for the token vault
    receipt_signing_key: SecretStr = SecretStr("")  # base64 Ed25519 private key (32 bytes)
    keys_dir: Path = BACKEND_ROOT / "data" / "keys"

    # Router: any low-confidence entity keeps the request local (fail closed).
    route_low_confidence_local: bool = True
    default_dial: Literal["max_privacy", "balanced", "max_quality"] = "balanced"

    admin_api_key: SecretStr = SecretStr("")

    @field_validator("unmatched_entity_action", mode="before")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper() if isinstance(value, str) else value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
