"""No-auth enrichment from the public t.me web preview.

Fetches https://t.me/<handle> - the page Telegram serves to logged-out browsers -
and reads its Open Graph tags and the little stat line. For a channel this yields
the title, description and subscriber count; for a user, their display name and
bio when public. Best-effort: private accounts / no-@username return a 'nothing
public' lead. The parser is split out so it can be unit-tested offline.
"""

from __future__ import annotations

import re

from .base import EnrichmentResult, Finding, Provider, Subject, register

_UA = {"User-Agent": "Mozilla/5.0 (compatible; TelegramTools/1.0; OSINT)"}

# Telegram's logged-out page uses these fillers when there's nothing real to show.
_FILLER = ("You can view and join", "If you have Telegram, you can", "You can contact",
           "Telegram: Contact", "Telegram Messenger")


def _og(prop: str, html: str):
    m = re.search(rf'<meta property="og:{prop}" content="(.*?)"\s*/?>', html, re.S)
    if not m:
        return None
    # minimal HTML-entity unescape for the few that show up in og tags
    import html as _h
    return _h.unescape(m.group(1)).strip()


def parse_preview(html: str, handle: str, url: str) -> list:
    """Turn a t.me preview page into findings. Pure, so it's testable offline."""
    findings: list = []
    title = _og("title", html)
    desc = _og("description", html)
    image = _og("image", html)

    if title and not any(f in title for f in _FILLER):
        findings.append(Finding("t.me", "profile", f"Display name: {title}", url=url,
                                confidence="confirmed", detail={"photo": image} if image else {}))
    if desc and not any(f in desc for f in _FILLER):
        findings.append(Finding("t.me", "bio", desc))

    extra = re.search(r'tgme_page_extra"\s*>(.*?)<', html, re.S)
    if extra:
        stat = re.sub(r"\s+", " ", extra.group(1)).strip()
        if stat:
            findings.append(Finding("t.me", "stat", stat, confidence="confirmed"))

    if "tgme_page_verified" in html or "verified_icon" in html:
        findings.append(Finding("t.me", "flag", "Verified badge shown on t.me",
                                confidence="confirmed"))

    if not findings:
        findings.append(Finding("t.me", "lead",
                                f"No public preview for @{handle} (private, a user without a "
                                "public profile, or no @username).", url=url))
    return findings


class TmeProvider(Provider):
    name = "t.me"
    label = "t.me public preview"
    needs_creds = False

    def available(self) -> tuple:
        try:
            import requests  # noqa: F401
            return True, ""
        except ImportError:
            return False, "The 'requests' package is required."

    def enrich(self, subject: Subject) -> EnrichmentResult:
        h = subject.handle()
        if not h:
            return EnrichmentResult(self.name, ok=False,
                                    error="No @username - t.me preview needs a public handle.")
        import requests
        url = f"https://t.me/{h}"
        try:
            r = requests.get(url, timeout=15, headers=_UA)
            r.raise_for_status()
        except Exception as exc:   # network / HTTP - surface it, don't crash
            return EnrichmentResult(self.name, ok=False, error=str(exc))
        return EnrichmentResult(self.name, findings=parse_preview(r.text, h, url))


register(TmeProvider())
