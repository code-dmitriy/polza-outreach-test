"""Секреты читаем из .env рядом с проектом, в код и в git они не попадают.

Отдельной зависимости ради трёх строк не тянем: формат .env тут простой —
KEY=VALUE, комментарии с #, кавычки по краям снимаются.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


@lru_cache(maxsize=1)
def _load_env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get(name: str, default: str = "") -> str:
    """Переменная окружения имеет приоритет над .env — так удобнее в CI."""
    return os.environ.get(name) or _load_env_file().get(name, default)


def hh_token() -> str:
    return get("HH_TOKEN")


def anthropic_key() -> str:
    return get("ANTHROPIC_API_KEY")
