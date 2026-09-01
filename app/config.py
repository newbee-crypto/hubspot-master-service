"""
Environment-driven configuration for HubSpot Master Service (§10.8).
All settings loaded from environment variables / .env file.
"""

import json
import logging
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings grouped per §10.8 of DESIGN.md."""

    # --- App Metadata ---
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # --- Database ---
    DATABASE_URL: str = "postgresql://hubspot_user:hubspot_pass@localhost:5432/hubspot_service"
    DATABASE_POOL_SIZE: int = 10

    # --- HubSpot API ---
    HUBSPOT_CLIENT_ID: str = ""
    HUBSPOT_CLIENT_SECRET: str = ""
    HUBSPOT_API_BASE_URL: str = "https://api.hubapi.com"
    HUBSPOT_API_VERSION: str = "v3"
    HUBSPOT_REQUEST_TIMEOUT: int = 30

    # --- HubSpot Rate Limiting ---
    HUBSPOT_BURST_LIMIT: int = 100
    HUBSPOT_DAILY_LIMIT: int = 250000
    HUBSPOT_RATE_LIMIT_WINDOW_SECONDS: int = 10
    HUBSPOT_RATE_LIMIT_RETRY_AFTER_FALLBACK: int = 10

    # --- HubSpot Pagination ---
    HUBSPOT_DEFAULT_PAGE_SIZE: int = 100
    HUBSPOT_MAX_PAGE_SIZE: int = 100

    # --- MinIO ---
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "hubspot-data"
    MINIO_SECURE: bool = False

    # --- Resilience ---
    EXTERNAL_CALL_MAX_RETRIES: int = 3
    EXTERNAL_CALL_RETRY_DELAYS: str = "1,2,4"
    EXTERNAL_CALL_JITTER: float = 0.5
    DLQ_PAYLOAD_MAX_BYTES: int = 10000

    # --- HMAC Authentication ---
    HMAC_ENABLED: bool = True
    HMAC_SECRET_KEY_CORE: str = ""
    HMAC_SECRET_KEY_ENGINEER: str = ""
    HMAC_SIGNATURE_MAX_AGE: int = 300
    HMAC_CLIENT_CONFIG: str = "{}"

    # --- Heartbeat ---
    HEARTBEAT_INTERVAL_SECONDS: int = 30
    HEARTBEAT_STALE_TIMEOUT_MINUTES: int = 5

    # --- Encryption ---
    ENCRYPTION_KEY: str = ""

    # --- Data Storage ---
    DATA_DIR: str = "./data"

    @property
    def retry_delays(self) -> List[float]:
        """Parse comma-separated retry delays into a list of floats."""
        return [float(d.strip()) for d in self.EXTERNAL_CALL_RETRY_DELAYS.split(",")]

    @property
    def hmac_client_config_parsed(self) -> dict:
        """Parse HMAC client config JSON string."""
        try:
            return json.loads(self.HMAC_CLIENT_CONFIG)
        except (json.JSONDecodeError, TypeError):
            return {}

    @property
    def is_production(self) -> bool:
        return self.APP_ENV in ("production", "staging")

    def validate_production_settings(self) -> None:
        """
        Fail fast at startup if production/staging settings are unsafe.
        Rejects placeholder secrets, disabled HMAC, etc.
        """
        if not self.is_production:
            return

        errors = []

        # HMAC must be enabled
        if not self.HMAC_ENABLED:
            errors.append("HMAC_ENABLED must be true in production/staging")

        # Check for placeholder secrets
        placeholder_indicators = ["change-me", "your-", "placeholder", "example", "test"]
        secret_fields = {
            "HMAC_SECRET_KEY_CORE": self.HMAC_SECRET_KEY_CORE,
            "HMAC_SECRET_KEY_ENGINEER": self.HMAC_SECRET_KEY_ENGINEER,
        }
        for field_name, value in secret_fields.items():
            if not value:
                errors.append(f"{field_name} must not be empty in production/staging")
            elif any(p in value.lower() for p in placeholder_indicators):
                errors.append(f"{field_name} appears to contain a placeholder value")

        # Database URL check
        if "hubspot_pass" in self.DATABASE_URL:
            errors.append("DATABASE_URL appears to contain placeholder credentials")

        if errors:
            raise ValueError(
                f"Production/staging configuration validation failed:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": True}


def get_settings() -> Settings:
    """Create and optionally validate settings."""
    settings = Settings()
    settings.validate_production_settings()
    return settings
