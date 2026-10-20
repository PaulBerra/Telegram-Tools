"""Typed exceptions for the Telegram core layer.

The core never prints and never calls sys.exit: it raises these so the CLI and
GUI can decide how to surface a problem.
"""

from __future__ import annotations

from typing import Optional


class TelegramError(Exception):
    """Base class for every error raised by the core layer."""


class NetworkError(TelegramError):
    """The HTTP request could not be completed (timeout, DNS, connection reset).

    Distinct from APIError: here Telegram never answered, so retrying later may work.
    """


class APIError(TelegramError):
    """Telegram answered with ``{"ok": false}``.

    Carries the raw ``error_code`` and ``description`` so callers can branch on
    them (e.g. 400 "message to forward not found" is a skip, not a fatal stop).
    """

    def __init__(self, error_code: Optional[int], description: str,
                 method: Optional[str] = None):
        self.error_code = error_code
        self.description = description
        self.method = method
        super().__init__(f"{method or '?'} -> [{error_code}] {description}")


class RateLimited(APIError):
    """HTTP 429. ``retry_after`` is the number of seconds Telegram asked us to wait.

    The client honours this automatically; this is only raised if the retry
    budget is exhausted.
    """

    def __init__(self, description: str, retry_after: int,
                 method: Optional[str] = None):
        self.retry_after = retry_after
        super().__init__(429, description, method)
