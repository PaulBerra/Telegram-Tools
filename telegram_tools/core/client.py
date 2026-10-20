"""HTTP client for the Telegram Bot API.

One place owns every network concern: base URL, timeouts, bounded retries on
transient network failures, and honouring ``parameters.retry_after`` on HTTP 429
(no more recursion + fixed sleep). Parameters are sent as a JSON body via POST so
they never land in a URL query string (and thus never in request logs); the token
still sits in the URL path, which the Bot API makes unavoidable.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping, Optional

import requests

from .errors import APIError, NetworkError, RateLimited

DEFAULT_BASE_URL = "https://api.telegram.org"
# (connect timeout, read timeout) in seconds.
DEFAULT_TIMEOUT = (5.0, 30.0)


class TelegramClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
        max_network_retries: int = 3,
        max_rate_limit_retries: int = 5,
        max_retry_after: int = 300,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not token or ":" not in token:
            raise ValueError("A Telegram bot token looks like '123456:ABC-...'.")
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.max_network_retries = max_network_retries
        self.max_rate_limit_retries = max_rate_limit_retries
        self.max_retry_after = max_retry_after
        self._sleep = sleep

    @property
    def bot_id(self) -> str:
        """The numeric bot id, which is the part of the token before the colon."""
        return self.token.split(":", 1)[0]

    def call(
        self,
        method: str,
        params: Optional[Mapping[str, Any]] = None,
        *,
        http_method: str = "POST",
    ) -> Any:
        """Call a Bot API method and return its ``result``, or raise.

        Retries transient network failures (bounded) and 429s (honouring
        ``retry_after``, bounded). Any other ``ok: false`` becomes an APIError.
        """
        url = f"{self.base_url}/bot{self.token}/{method}"
        payload = {k: v for k, v in (params or {}).items() if v is not None}

        network_attempts = 0
        rate_attempts = 0
        while True:
            try:
                if http_method.upper() == "GET":
                    resp = self.session.get(url, params=payload, timeout=self.timeout)
                else:
                    resp = self.session.post(url, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                network_attempts += 1
                if network_attempts > self.max_network_retries:
                    raise NetworkError(f"{method}: {exc}") from exc
                self._sleep(min(2 ** network_attempts, 10))
                continue

            try:
                data = resp.json()
            except ValueError as exc:
                raise APIError(resp.status_code, f"non-JSON response: {resp.text[:200]!r}",
                               method) from exc

            if data.get("ok"):
                return data.get("result")

            code = data.get("error_code")
            desc = data.get("description", "unknown error")

            if code == 429:
                retry_after = int(data.get("parameters", {}).get("retry_after", 1))
                rate_attempts += 1
                if rate_attempts > self.max_rate_limit_retries or retry_after > self.max_retry_after:
                    raise RateLimited(desc, retry_after, method)
                self._sleep(retry_after)
                continue

            raise APIError(code, desc, method)
