"""Offline tests for the no-auth enrichment providers (no network)."""

from telegram_tools.core import enrich
from telegram_tools.core.enrich import dorks, tme
from telegram_tools.core.enrich.base import Subject


def test_providers_registered():
    names = {p.name for p in enrich.providers()}
    assert {"dorks", "t.me", "tgstat", "telethon"} <= names


def test_tgstat_parse_ok_and_error():
    from telegram_tools.core.enrich import tgstat
    ok = {"status": "ok", "response": {"title": "Scam Hub", "username": "scamhub",
          "participants_count": 54321, "category": "Crypto", "about": "pump signals"}}
    kinds = {f.kind: f.value for f in tgstat.parse_channel(ok, "scamhub")}
    assert "Scam Hub" in kinds["profile"] or "54321" in kinds.get("stat", "")
    stats = [f.value for f in tgstat.parse_channel(ok, "scamhub")]
    assert any("54321 subscribers" in s for s in stats)
    err = tgstat.parse_channel({"status": "error", "error": "token invalid"}, "x")
    assert len(err) == 1 and err[0].kind == "lead" and "token invalid" in err[0].value


def test_tgstat_not_ready_without_token(tmp_path, monkeypatch):
    from telegram_tools.core import creds
    monkeypatch.setattr(creds, "_CREDS", str(tmp_path / "none.json"))
    from telegram_tools.core.enrich.tgstat import TgstatProvider
    ok, why = TgstatProvider().ready()
    assert ok is False and "Keys" in why


def test_dorks_build_real_leads():
    res = dorks.DorksProvider().enrich(Subject(username="Scammer", user_id=42))
    assert res.ok and res.findings
    urls = [f.url for f in res.findings if f.url]
    assert any("t.me/Scammer" in u for u in urls)
    assert any("site%3At.me" in u for u in urls)   # site:t.me, url-encoded
    assert any("lyzem.com/search" in u for u in urls)
    assert any("42" in u for u in urls)            # numeric-id lead


def test_dorks_needs_an_identifier():
    assert dorks.DorksProvider().enrich(Subject()).ok is False


def test_tme_parse_channel_preview():
    html = '''
    <meta property="og:title" content="Crypto Scams Hub"/>
    <meta property="og:description" content="Daily pump signals, DM @admin"/>
    <meta property="og:image" content="https://cdn.telegram.org/x.jpg"/>
    <div class="tgme_page_extra">12 345 subscribers</div>
    '''
    findings = tme.parse_preview(html, "cryptoscamshub", "https://t.me/cryptoscamshub")
    kinds = {f.kind: f.value for f in findings}
    assert "Crypto Scams Hub" in kinds.get("profile", "")
    assert "pump signals" in kinds.get("bio", "")
    assert "12 345 subscribers" in kinds.get("stat", "")


def test_tme_parse_empty_preview_gives_lead():
    html = '''
    <meta property="og:title" content="Telegram: Contact @ghost"/>
    <meta property="og:description" content="If you have Telegram, you can contact @ghost right away."/>
    '''
    findings = tme.parse_preview(html, "ghost", "https://t.me/ghost")
    assert len(findings) == 1 and findings[0].kind == "lead"


def test_telethon_provider_unavailable_without_creds(tmp_path, monkeypatch):
    # With no creds, the provider must report itself unavailable, not crash.
    from telegram_tools.core import creds
    monkeypatch.setattr(creds, "_CREDS", str(tmp_path / "none.json"))
    from telegram_tools.core.enrich.telethon_provider import TelethonProvider
    ok, why = TelethonProvider().available()
    assert ok is False and "Keys tab" in why
