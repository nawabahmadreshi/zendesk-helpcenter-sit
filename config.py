from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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

    # ── AI Help System ──────────────────────────────────────────────
    AI_PROVIDER: str = field(default_factory=lambda: os.environ.get("AI_PROVIDER", "gemini").lower())
    # Fallback mode: 'gemini' | 'openrouter' | 'ollama' | 'local' | 'auto'
    # 'auto' = Gemini first, fallback to OpenRouter, then local on failure
    AI_FALLBACK_MODE: str = field(default_factory=lambda: os.environ.get("AI_FALLBACK_MODE", "gemini").lower())

    # Gemini
    GEMINI_API_KEY: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", ""))
    GEMINI_MODEL: str = field(default_factory=lambda: os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"))

    # OpenRouter (openai-compatible, cheap/free models)
    OPENROUTER_API_KEY: str = field(default_factory=lambda: os.environ.get("OPENROUTER_API_KEY", ""))
    OPENROUTER_MODEL: str = field(default_factory=lambda: os.environ.get("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free"))
    OPENROUTER_SITE_URL: str = field(default_factory=lambda: os.environ.get("OPENROUTER_SITE_URL", "http://localhost:8000"))

    # Ollama (local daemon — must be running separately)
    OLLAMA_BASE_URL: str = field(default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"))
    OLLAMA_MODEL: str = field(default_factory=lambda: os.environ.get("OLLAMA_MODEL", "phi3:mini"))
    OLLAMA_EMBED_MODEL: str = field(default_factory=lambda: os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"))

    # ── Background Sync ───────────────────────────────────────────
    AUTO_SYNC_ENABLED: bool = field(default_factory=lambda: os.environ.get("AUTO_SYNC_ENABLED", "1") == "1")
    AUTO_SYNC_INTERVAL_MINS: int = field(default_factory=lambda: int(os.environ.get("AUTO_SYNC_INTERVAL_MINS", "30")))

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

    @property
    def vectordb_dir(self) -> Path:
        return self.STORAGE_DIR / "vectordb"

    def ensure_dirs(self) -> None:
        """Create all storage sub-directories if they don't exist."""
        for d in (self.raw_dir, self.processed_dir, self.metadata_dir, self.published_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ── admin panel methods ────────────────────────────────────────────
    def get_all_settings(self) -> dict:
        """Return all settings grouped and with secrets masked for the UI."""
        def mask(val: str) -> str:
            if not val:
                return ""
            if len(val) <= 8:
                return "••••••••"
            return val[:4] + "••••" + val[-4:]

        return {
            "zendesk": {
                "ZENDESK_SUBDOMAIN": self.ZENDESK_SUBDOMAIN,
                "ZENDESK_EMAIL": self.ZENDESK_EMAIL,
                "ZENDESK_API_TOKEN": mask(self.ZENDESK_API_TOKEN),
                "ZENDESK_CATEGORY_ID": str(self.ZENDESK_CATEGORY_ID),
                "ZENDESK_LOCALE": self.ZENDESK_LOCALE,
                "ZENDESK_WEBHOOK_SECRET": mask(self.ZENDESK_WEBHOOK_SECRET),
            },
            "ai": {
                "AI_PROVIDER": self.AI_PROVIDER,
                "AI_FALLBACK_MODE": self.AI_FALLBACK_MODE,
                "GEMINI_API_KEY": mask(self.GEMINI_API_KEY),
                "GEMINI_MODEL": self.GEMINI_MODEL,
                "OPENROUTER_API_KEY": mask(self.OPENROUTER_API_KEY),
                "OPENROUTER_MODEL": self.OPENROUTER_MODEL,
                "OPENROUTER_SITE_URL": self.OPENROUTER_SITE_URL,
                "OLLAMA_BASE_URL": self.OLLAMA_BASE_URL,
                "OLLAMA_MODEL": self.OLLAMA_MODEL,
            },
            "slack": {
                "SLACK_WEBHOOK_URL": mask(self.SLACK_WEBHOOK_URL),
            },
            "storage": {
                "STORAGE_DIR": str(self.STORAGE_DIR),
            },
            "background_sync": {
                "AUTO_SYNC_ENABLED": "1" if self.AUTO_SYNC_ENABLED else "0",
                "AUTO_SYNC_INTERVAL_MINS": str(self.AUTO_SYNC_INTERVAL_MINS),
            },
        }

    @staticmethod
    def save_to_env(updates: dict) -> None:
        """Write updated key=value pairs to the .env file and hot-reload os.environ."""
        env_path = Path(".env")
        lines: list = []
        written_keys: set = set()

        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in updates:
                        lines.append(f'{key}={updates[key]}')
                        written_keys.add(key)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)

        # Append new keys not previously in the file
        for key, value in updates.items():
            if key not in written_keys:
                lines.append(f'{key}={value}')

        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Hot-reload so the running process picks up changes
        for key, value in updates.items():
            os.environ[key] = str(value)

    # ── factory ────────────────────────────────────────────────────────
    def get_zendesk_client(self):
        from app.zendesk_client import ZendeskClient

        return ZendeskClient(
            subdomain=self.ZENDESK_SUBDOMAIN,
            email=self.ZENDESK_EMAIL,
            api_token=self.ZENDESK_API_TOKEN,
            locale=self.ZENDESK_LOCALE,
        )
