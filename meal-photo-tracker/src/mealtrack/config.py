"""Paths and settings, all overridable through environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_GOAL_KCAL = 2000
DEFAULT_GOAL_WATER_ML = 2000


def load_env() -> None:
    """Load a local .env file if there is one (it never overrides real env vars)."""
    load_dotenv(override=False)


def home() -> Path:
    return Path(os.getenv("MEALTRACK_HOME", ".mealtrack"))


def db_path(backend: str | None = None) -> Path:
    """Where the log lives. Mock data never touches the real log."""
    explicit = os.getenv("MEALTRACK_DB")
    if explicit:
        return Path(explicit)
    return home() / ("demo.db" if backend == "mock" else "log.db")


def cache_dir() -> Path:
    return Path(os.getenv("MEALTRACK_CACHE_DIR", str(home() / "cache")))


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


def goal_kcal() -> int:
    return _int_env("MEALTRACK_GOAL_KCAL", DEFAULT_GOAL_KCAL)


def goal_water_ml() -> int:
    return _int_env("MEALTRACK_GOAL_WATER_ML", DEFAULT_GOAL_WATER_ML)
