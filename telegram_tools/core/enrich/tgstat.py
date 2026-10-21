"""TGStat enrichment - a catalogue/analytics API, no Telegram login.

TGStat indexes millions of public channels/groups. You register at tgstat.ru,
get an API token (there's a free Stat tier), and query it over plain HTTP - no
Telegram account, no bot-to-bot (which Telegram forbids anyway). The token lives
in the Keys tab. This resolves a @handle to TGStat's record: title, subscriber
count, category, country, description.

Note: TGStat covers channels/public groups, not arbitrary users, and some methods
need a paid tariff - the provider surfaces TGStat's own error text when so.
"""

from __future__ import annotations

from .base import EnrichmentResult, Finding, Provider, Subject, register

API = "https://api.tgstat.ru"


def parse_channel(data: dict, handle: str) -> list:
    """TGStat /channels/get JSON -> findings. Pure, so it's testable offline."""
    if not isinstance(data, dict) or data.get("status") != "ok":
        err = (data or {}).get("error") or "no record (not a public channel, or tariff-limited)"
        return [Finding("tgstat", "lead", f"TGStat: {err}")]
    r = data.get("response") or {}
    findings: list = []
    link = r.get("link") or ""
    if link and not link.startswith("http"):
        link = "https://" + link        # TGStat returns 't.me/Name' without a scheme
    if r.get("title"):
        findings.append(Finding("tgstat", "profile", f"Channel: {r['title']}",
                                url=link or None, confidence="confirmed"))
    if r.get("username"):
        findings.append(Finding("tgstat", "alias", "@" + str(r["username"]).lstrip("@")))
    if r.get("participants_count") is not None:
        findings.append(Finding("tgstat", "stat",
                                f"{r['participants_count']} subscribers", confidence="confirmed"))
    for key, lbl in (("category", "Category"), ("country", "Country"), ("language", "Language")):
        if r.get(key):
            findings.append(Finding("tgstat", "profile", f"{lbl}: {r[key]}"))
    if r.get("about"):
        findings.append(Finding("tgstat", "bio", str(r["about"]).strip()))
    if not findings:
        findings.append(Finding("tgstat", "lead", "TGStat returned no usable fields."))
    return findings


class TgstatProvider(Provider):
    name = "tgstat"
    label = "TGStat channel stats (API token, no Telegram login)"
    needs_creds = True

    def ready(self) -> tuple:
        from .. import creds
        try:
            import requests  # noqa: F401
        except ImportError:
            return False, "The 'requests' package is required."
        if not creds.load_credentials().get("tgstat_key"):
            return False, "Set a TGStat API token in the Keys tab (free tier at tgstat.ru)."
        return True, ""

    def available(self) -> tuple:
        return self.ready()

    def enrich(self, subject: Subject) -> EnrichmentResult:
        ok, why = self.ready()
        if not ok:
            return EnrichmentResult(self.name, ok=False, error=why)
        h = subject.handle()
        if not h:
            return EnrichmentResult(self.name, ok=False,
                                    error="Needs a @username / channel handle.")
        import requests
        from .. import creds
        token = creds.load_credentials()["tgstat_key"]
        try:
            r = requests.get(f"{API}/channels/get",
                             params={"token": token, "channelId": "@" + h}, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            return EnrichmentResult(self.name, ok=False, error=str(exc))
        return EnrichmentResult(self.name, findings=parse_channel(data, h))


register(TgstatProvider())
