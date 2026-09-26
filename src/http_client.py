"""Вежливый HTTP-клиент с файловым кешем.

Кеш нужен не для скорости, а для воспроизводимости: проверяющий запустит
скрипт через несколько дней, сайт может лежать — результат не должен «плыть».
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from . import config

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
UA = "Mozilla/5.0 (compatible; PolzaOutreachBot/1.0; +research contact enrichment)"

_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})
_last_hit: dict[str, float] = {}
DELAY_PER_HOST = 1.0  # секунда между запросами к одному хосту


def _cache_path(url: str, ext: str = ".html") -> Path:
    return CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest()[:24] + ext)


def _auth_headers(url: str) -> dict[str, str]:
    """API hh.ru с 2025 года отвечает 403 без токена зарегистрированного
    приложения. Токен лежит в .env, в кеш и в логи не попадает."""
    if "api.hh.ru" in url:
        token = config.hh_token()
        if token:
            return {"Authorization": f"Bearer {token}"}
    return {}


def _throttle(url: str) -> None:
    host = url.split("/")[2] if "://" in url else url
    since = time.time() - _last_hit.get(host, 0.0)
    if since < DELAY_PER_HOST:
        time.sleep(DELAY_PER_HOST - since)
    _last_hit[host] = time.time()


def fetch_json(url: str, params: dict | None = None, timeout: int = 15,
               use_cache: bool = True) -> dict | None:
    """GET с JSON-ответом и тем же файловым кешем, что и у HTML."""
    key = url + "?" + urlencode(sorted((params or {}).items()))
    path = _cache_path(key, ".json")
    if use_cache and path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            path.unlink(missing_ok=True)

    _throttle(url)
    try:
        resp = _session.get(url, params=params, timeout=timeout,
                            headers=_auth_headers(url))
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.debug("fetch_json failed %s: %s", url, exc)
        return None

    CACHE_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def fetch(url: str, timeout: int = 12, use_cache: bool = True) -> str | None:
    """Вернуть HTML страницы или None. Исключения наружу не пробрасываем:
    в пакетной обработке одна упавшая компания не должна ронять прогон."""
    path = _cache_path(url)
    if use_cache and path.exists():
        return path.read_text(encoding="utf-8", errors="ignore")

    _throttle(url)
    try:
        resp = _session.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        log.debug("fetch failed %s: %s", url, exc)
        return None

    if resp.status_code >= 400:
        log.debug("fetch %s -> HTTP %s", url, resp.status_code)
        return None

    # requests плохо угадывает кодировку для старых рунет-сайтов на windows-1251
    if resp.encoding and resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"

    html = resp.text
    CACHE_DIR.mkdir(exist_ok=True)
    path.write_text(html, encoding="utf-8", errors="ignore")
    return html
