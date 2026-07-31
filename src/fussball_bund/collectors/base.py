"""采集器基类：HTTP session、重试、速率控制。"""
from __future__ import annotations

import time
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from fussball_bund.config import settings
from fussball_bund.storage.db import Database

logger = logging.getLogger(__name__)


class BaseCollector:
    """所有采集器的公共基类。"""

    name: str = "base"

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        retry = Retry(
            total=settings.request_retries,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        s.headers.update({"User-Agent": settings.user_agent})
        return s

    def _get(self, url: str, params: dict | None = None, **kw) -> requests.Response:
        resp = self.session.get(
            url, params=params, timeout=settings.request_timeout, **kw
        )
        resp.raise_for_status()
        return resp

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)
