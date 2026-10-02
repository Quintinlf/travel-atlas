"""Load travel/.env into os.environ without overwriting existing vars."""

from __future__ import annotations

import os
from pathlib import Path

_TRAVEL_ROOT = Path(__file__).resolve().parent.parent


def load_travel_env(*, env_path: Path | None = None) -> Path | None:
    """Load KEY=VALUE pairs from travel/.env into os.environ.

    Existing environment variables win. Never logs secret values.
    Returns the path loaded, or None if the file is missing.
    """
    path = env_path or (_TRAVEL_ROOT / ".env")
    if not path.is_file():
        return None
    try:
        from dotenv import load_dotenv

        load_dotenv(path, override=False)
        return path
    except ImportError:
        pass
    _parse_env_file(path)
    return path


def _parse_env_file(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
