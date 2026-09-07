"""Application configuration loaded from environment variables.

Uses pydantic-settings v2 for typed, validated settings with .env support.
All settings are read-only after startup.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    app_secret_key: str = Field(..., min_length=16)
    debug: bool = False

    # ── Database ──────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/vasp_engine"
    )
    database_sync_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/vasp_engine"
    )
    # Column-level encryption key (must be set in production)
    db_encryption_key: str = Field(..., min_length=1)

    # ── Redis ─────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # ── JWT ───────────────────────────────────────────────────
    jwt_secret_key: str = Field(..., min_length=16)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_hours: int = 8
    jwt_refresh_token_expire_days: int = 30
    jwt_key_rotation_days: int = 90

    # ── Blockchain API keys ───────────────────────────────────
    etherscan_api_key: str = ""
    bscscan_api_key: str = ""
    polygonscan_api_key: str = ""
    solscan_api_key: str = ""

    # ── Gemini LLM ────────────────────────────────────────────
    gemini_api_key: str = ""

    # ── Mistral AI ────────────────────────────────────────────
    mistral_api_key: str = ""

    # ── Nansen (wallet intelligence) ──────────────────────────
    nansen_api_key: str = ""

    # ── Bitcoin Abuse DB ──────────────────────────────────────
    bitcoin_abuse_api_key: str = ""

    # ── Intel sync schedule ───────────────────────────────────
    intel_sync_interval_hours: int = 24

    # ── Blockchain cache ──────────────────────────────────────
    blockchain_cache_ttl: int = 1800  # seconds

    # ── Object storage (S3 / MinIO) ───────────────────────────
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_bucket_name: str = "vasp-engine-reports"
    s3_region: str = "us-east-1"

    # ── SAHYOG Portal ─────────────────────────────────────────
    sahyog_endpoint_url: str = ""
    sahyog_auth_type: Literal["api_key", "oauth2"] = "api_key"
    sahyog_api_key: str = ""

    # ── Audit log ─────────────────────────────────────────────
    audit_max_size_bytes: int = 10 * 1024 * 1024 * 1024  # 10 GB

    # ── Rate limiting ─────────────────────────────────────────
    rate_limit_per_minute: int = 100

    # ── Queue ─────────────────────────────────────────────────
    trace_queue_depth_limit: int = 100

    # ── CORS ──────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str) -> str:
        """Accept comma-separated origins string."""
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS origins as a Python list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (reads env once at startup)."""
    return Settings()
