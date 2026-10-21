"""No-auth 'open in browser' leads: public search engines & Telegram indexers.

Telegram has no index of who's in which group, so investigators pivot through
public search. This provider builds the right query URLs for a handle - nothing
is fetched or scraped here, the user opens them. Always available, no account.
"""

from __future__ import annotations

import urllib.parse

from .base import EnrichmentResult, Finding, Provider, Subject, register


def _q(s: str) -> str:
    return urllib.parse.quote(s)


class DorksProvider(Provider):
    name = "dorks"
    label = "Search the open web (leads to open in a browser)"
    needs_creds = False

    def enrich(self, subject: Subject) -> EnrichmentResult:
        h = subject.handle()
        findings: list = []
        if h:
            findings += [
                Finding("dorks", "lead", f"Telegram profile / preview for @{h}",
                        url=f"https://t.me/{h}"),
                Finding("dorks", "lead", f"Google: where @{h} appears on t.me",
                        url="https://www.google.com/search?q=" + _q(f'site:t.me "@{h}"')),
                Finding("dorks", "lead", f"Google: @{h} in public channel previews (t.me/s)",
                        url="https://www.google.com/search?q=" + _q(f'site:t.me/s "@{h}"')),
                Finding("dorks", "lead", f"Lyzem index search for @{h}",
                        url="https://lyzem.com/search?q=" + _q("@" + h) + "&f=all"),
                Finding("dorks", "lead", f"TGStat channel stats for @{h}",
                        url=f"https://tgstat.com/channel/@{h}"),
                Finding("dorks", "lead", f"DuckDuckGo: @{h} across t.me",
                        url="https://duckduckgo.com/?q=" + _q(f'site:t.me "@{h}"')),
            ]
        if subject.user_id:
            findings.append(Finding("dorks", "lead", f"Google for the numeric id {subject.user_id}",
                                    url="https://www.google.com/search?q="
                                        + _q(f'"{subject.user_id}" telegram')))
        if not findings:
            return EnrichmentResult(self.name, ok=False,
                                    error="Need a @username or id to build search leads.")
        return EnrichmentResult(self.name, findings=findings)


register(DorksProvider())
