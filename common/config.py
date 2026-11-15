"""Loads YAML configuration and environment variables."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
PROMPTS_DIR = ROOT / "prompts"

try:  # .env is optional (GitHub Actions uses secrets instead)
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


def _load_yaml(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=None)
def settings() -> dict[str, Any]:
    return _load_yaml("settings.yaml")


@lru_cache(maxsize=None)
def sources() -> dict[str, Any]:
    return _load_yaml("sources.yaml")


@lru_cache(maxsize=None)
def holidays_config() -> dict[str, Any]:
    return _load_yaml("nse_holidays.yaml")


@lru_cache(maxsize=None)
def events_config() -> dict[str, Any]:
    return _load_yaml("events_calendar.yaml")


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def resolve(path: str | Path) -> Path:
    """Resolve a repo-relative path."""
    p = Path(path)
    return p if p.is_absolute() else ROOT / p
