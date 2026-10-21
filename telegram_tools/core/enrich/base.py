"""Enrichment provider framework.

A provider takes a Subject (a user we're investigating) and returns Findings -
each labelled with its source and a confidence, so the UI can be honest about
where every scrap came from. Providers declare whether they need credentials;
the no-auth ones work out of the box, the credentialed ones light up only once
the user has set things up in the Keys tab.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Subject:
    """Who we're investigating: a user by id and/or @username."""
    user_id: Optional[int] = None
    username: Optional[str] = None
    label: str = ""

    def handle(self) -> Optional[str]:
        return self.username.lstrip("@") if self.username else None

    def display(self) -> str:
        return self.label or (("@" + self.handle()) if self.handle()
                              else (f"id {self.user_id}" if self.user_id else "unknown"))


@dataclass
class Finding:
    source: str                 # provider name: "t.me", "telethon", "dorks"
    kind: str                   # "profile" | "bio" | "group" | "flag" | "stat" | "lead" | "alias"
    value: str                  # human-readable text
    url: Optional[str] = None   # a link to open (dorks / t.me)
    confidence: str = "reported"   # "confirmed" | "reported" | "lead"
    detail: dict = field(default_factory=dict)


@dataclass
class EnrichmentResult:
    provider: str
    ok: bool = True
    error: str = ""
    findings: list = field(default_factory=list)


class Provider:
    """Base class. Subclasses set name/label/needs_creds and implement enrich()."""
    name = "base"
    label = "Base"
    needs_creds = False

    def available(self) -> tuple:
        """(ok, reason). The real check - may touch the network, so call it off
        the UI thread (inside enrich / a worker)."""
        return True, ""

    def ready(self) -> tuple:
        """Cheap, non-blocking check for button state on the UI thread. Defaults
        to available(); providers whose available() does I/O override this."""
        return self.available()

    def enrich(self, subject: Subject) -> EnrichmentResult:
        raise NotImplementedError


_REGISTRY: list = []


def register(provider: Provider) -> Provider:
    _REGISTRY.append(provider)
    return provider


def providers() -> list:
    return list(_REGISTRY)
