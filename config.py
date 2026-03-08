from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Centralised configuration loaded from environment variables."""

    ZENDESK_SUBDOMAIN: str = field(default_factory=lambda: os.environ["ZENDESK_SUBDOMAIN"])
    ZENDESK_EMAIL: str = field(default_factory=lambda: os.environ["ZENDESK_EMAIL"])
    ZENDESK_API_TOKEN: str = field(default_factory=lambda: os.environ["ZENDESK_API_TOKEN"])
    ZENDESK_CATEGORY_ID: int = field(default_factory=lambda: int(os.environ["ZENDESK_CATEGORY_ID"]))
    ZENDESK_LOCALE: str = field(default_factory=lambda: os.environ.get("ZENDESK_LOCALE", "en-us"))
    ZENDESK_WEBHOOK_SECRET: str = field(default_factory=lambda: os.environ.get("ZENDESK_WEBHOOK_SECRET", ""))

    SLACK_WEBHOOK_URL: str = field(default_factory=lambda: os.environ.get("SLACK_WEBHOOK_URL", ""))

    STORAGE_DIR: Path = field(default_factory=lambda: Path(os.environ.get("STORAGE_DIR", "storage")))

    # ── derived sub-paths ──────────────────────────────────────────────
    @property
    def raw_dir(self) -> Path:
        return self.STORAGE_DIR / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.STORAGE_DIR / "processed"

    @property
    def metadata_dir(self) -> Path:
        return self.STORAGE_DIR / "metadata"

    @property
    def published_dir(self) -> Path:
        return self.STORAGE_DIR / "published"

    @property
    def logs_dir(self) -> Path:
        return self.STORAGE_DIR / "logs"

    def ensure_dirs(self) -> None:
        """Create all storage sub-directories if they don't exist."""
        for d in (self.raw_dir, self.processed_dir, self.metadata_dir, self.published_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ── factory ────────────────────────────────────────────────────────
    def get_zendesk_client(self):
        from app.zendesk_client import ZendeskClient

        return ZendeskClient(
            subdomain=self.ZENDESK_SUBDOMAIN,
            email=self.ZENDESK_EMAIL,
            api_token=self.ZENDESK_API_TOKEN,
            locale=self.ZENDESK_LOCALE,
        )
