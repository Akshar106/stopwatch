"""Runtime configuration.

Non-secret settings come from environment variables. Secrets come from environment variables locally and
from SSM Parameter Store in AWS (``SSM_PREFIX``), loaded once per cold start.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Settings that may be supplied by SSM Parameter Store as /<prefix>/<name>.
SECRET_FIELDS: tuple[str, ...] = (
    "database_url",
    "database_owner_url",
    "google_client_secret",
    "session_secret",
    "vapid_private_key",
    "anthropic_api_key",
    "origin_verify_secret",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["local", "test", "staging", "prod"] = Field(default="local", alias="STOPWATCH_ENV")
    version: str = Field(default="dev", alias="STOPWATCH_VERSION")

    # Storage: file:///abs/path, file://relative/path, or s3://bucket[/prefix]
    lake_url: str = "file://.localdata/lake"
    site_url: str = "file://.localdata/site"

    agencies: str = "mbta"  # comma-separated agency ids (see platform/agencies.py)
    public_base_url: str = "http://localhost:5173"

    ingest_enabled: bool = True
    alerts_enabled: bool = False
    ask_enabled: bool = False
    demo_enabled: bool = True

    database_url: SecretStr | None = None
    database_owner_url: SecretStr | None = None

    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    session_secret: SecretStr | None = None

    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    vapid_subject: str = "mailto:operator@example.com"

    anthropic_api_key: SecretStr | None = None
    ask_model: str = "claude-opus-5-5"  # set ASK_MODEL=claude-haiku-5-5 to stretch the monthly cap
    ask_monthly_cap_usd: float = 1.0

    # Shared secret CloudFront adds as X-Origin-Verify on /api/* requests; the API rejects requests without it
    # in staging/prod so nobody can call API Gateway directly with forged viewer headers.
    origin_verify_secret: SecretStr | None = None

    notify_function_name: str | None = None
    ssm_prefix: str | None = None
    log_level: str = "INFO"

    @field_validator("agencies")
    @classmethod
    def _strip_agencies(cls, v: str) -> str:
        return ",".join(a.strip() for a in v.split(",") if a.strip())

    @property
    def agency_ids(self) -> list[str]:
        return self.agencies.split(",") if self.agencies else []

    @property
    def is_cloud(self) -> bool:
        return self.env in ("staging", "prod")


def _load_ssm_secrets(settings: Settings) -> Settings:
    """Fill unset secret fields from SSM Parameter Store (SecureString, KMS-decrypted)."""
    missing = [f for f in SECRET_FIELDS if getattr(settings, f) is None]
    if not settings.ssm_prefix or not missing:
        return settings
    import boto3  # imported lazily: not needed locally

    prefix = settings.ssm_prefix.rstrip("/")
    client = boto3.client("ssm")
    paginator = client.get_paginator("get_parameters_by_path")
    found: dict[str, str] = {}
    for page in paginator.paginate(Path=prefix, WithDecryption=True, Recursive=False):
        for param in page["Parameters"]:
            found[param["Name"].rsplit("/", 1)[-1]] = param["Value"]
    updates = {f: SecretStr(found[f]) for f in missing if f in found and found[f] != "unset"}
    # Non-secret values may also live in SSM for convenience.
    for plain in ("google_client_id", "vapid_public_key"):
        if getattr(settings, plain) is None and found.get(plain) not in (None, "unset"):
            updates[plain] = found[plain]  # type: ignore[assignment]
    return settings.model_copy(update=updates)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    if settings.ssm_prefix and os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        settings = _load_ssm_secrets(settings)
    return settings


def reset_settings_cache() -> None:
    """For tests."""
    get_settings.cache_clear()
