"""Enrichment providers: pull extra signal on a subject from outside the bots.

Importing this package registers the built-in providers. No-auth ones (dorks,
t.me) work immediately; the Telethon one is registered too but reports itself
unavailable until credentials + a login exist. Telethon is imported lazily, so
this package imports cleanly even without it installed.
"""

from __future__ import annotations

from .base import EnrichmentResult, Finding, Provider, Subject, providers, register
from . import dorks, tme, tgstat, telethon_provider   # noqa: F401  (registers on import)

__all__ = ["EnrichmentResult", "Finding", "Provider", "Subject", "providers", "register"]
