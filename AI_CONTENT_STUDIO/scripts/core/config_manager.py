"""Singleton configuration manager — reads settings.yaml + .env."""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

from .logger import get_logger

logger = get_logger(__name__)

_ENV_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "adobe_podcast": "ADOBE_PODCAST_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


class ConfigManager:
    """Thread-safe singleton that owns all runtime configuration."""

    _instance: Optional["ConfigManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        config_path: Optional[Path] = None,
        env_path: Optional[Path] = None,
    ) -> None:
        if getattr(self, "_ready", False):
            return

        self._cfg: dict = {}
        self._ready = False

        if config_path:
            self._load_yaml(config_path)
        if env_path and env_path.exists():
            load_dotenv(env_path)
            logger.info(f"Env vars loaded from {env_path}")
        else:
            load_dotenv()

        self._ready = True

    # ── Public API ─────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """Dot-notation lookup: config.get('api.openai.model')."""
        parts = key.split(".")
        node = self._cfg
        for part in parts:
            if not isinstance(node, dict):
                return default
            node = node.get(part)
            if node is None:
                return default
        return node

    def get_env(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return os.getenv(key, default)

    def get_api_key(self, service: str) -> Optional[str]:
        env_key = _ENV_KEY_MAP.get(service.lower())
        return os.getenv(env_key) if env_key else None

    @property
    def raw(self) -> dict:
        return self._cfg

    # ── Internal ───────────────────────────────────────────────

    def _load_yaml(self, path: Path) -> None:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                self._cfg = yaml.safe_load(fh) or {}
            logger.info(f"Config loaded: {path}")
        except FileNotFoundError:
            logger.error(f"Config file not found: {path}")
            raise
        except yaml.YAMLError as exc:
            logger.error(f"YAML parse error in {path}: {exc}")
            raise
