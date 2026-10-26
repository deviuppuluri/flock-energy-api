"""Settings for the application.

This file reads configuration (portal address, username, password, timeout)
from environment variables. During local development those variables come
from a private `.env` file that is NOT committed to Git (see `.gitignore`).

Why a separate file? Every other file asks `get_settings()` for values, so
secrets are never typed into the source code.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Reads the `.env` file (if it exists) and puts its values into os.environ.
load_dotenv()

DEFAULT_PORTAL_URL = "https://urja-ops.flockenergy.tech"
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Settings:
    """A simple, read-only bundle of settings."""

    portal_base_url: str
    portal_username: str
    portal_password: str
    request_timeout: float

    @property
    def has_credentials(self) -> bool:
        """True only if both username and password were provided."""
        return bool(self.portal_username and self.portal_password)


def _read_timeout() -> float:
    raw = os.getenv("REQUEST_TIMEOUT_SECONDS", "")
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def get_settings() -> Settings:
    """Build a Settings object from the current environment."""
    return Settings(
        portal_base_url=os.getenv("PORTAL_BASE_URL", DEFAULT_PORTAL_URL).rstrip("/"),
        portal_username=os.getenv("PORTAL_USERNAME", ""),
        portal_password=os.getenv("PORTAL_PASSWORD", ""),
        request_timeout=_read_timeout(),
    )
