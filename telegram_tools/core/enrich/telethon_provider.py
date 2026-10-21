"""Credentialed enrichment through the user's own account (Telethon / MTProto).

This is the powerful path: resolve a @username or id to a real entity, read the
scam/fake flags Telegram itself sets, and - the big one - list the groups in
COMMON with the target (getCommonChats), which directly ties an actor to its
network. It needs api_id/api_hash + a logged-in session (Keys tab), so it's
opt-in. Every import of Telethon/mtproto is lazy, so this module is always safe
to import even when Telethon isn't installed.
"""

from __future__ import annotations

from .base import EnrichmentResult, Finding, Provider, Subject, register


class TelethonProvider(Provider):
    name = "telethon"
    label = "Your account via Telethon (common groups, flags, real id)"
    needs_creds = True

    def _config(self):
        from .. import creds
        from ...mtproto.client import MTProtoConfig   # lazy: imports Telethon
        c = creds.load_credentials()
        return MTProtoConfig(api_id=int(c["tg_api_id"]), api_hash=c["tg_api_hash"],
                             session=creds.SESSION, phone=c.get("tg_phone") or None)

    @staticmethod
    def _ensure_loop() -> None:
        # Telethon (telethon.sync) needs an asyncio event loop in the CURRENT
        # thread. Enrichment runs in a background worker thread, which has no loop
        # by default on Python 3.12+, so build/connect would fail there. Give the
        # thread a fresh loop. (The login flow happens to run early enough to have
        # one; the enrich worker does not, which is why only this path broke.)
        import asyncio
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

    def ready(self) -> tuple:
        # Cheap check for the UI: creds present + Telethon importable, no connect.
        from .. import creds
        if not creds.has_telethon_creds():
            return False, "Set api_id / api_hash and log in (Keys tab)."
        try:
            import telethon  # noqa: F401
        except Exception as exc:   # surface the REAL error, don't assume "missing"
            return False, f"Telethon import failed: {exc}"
        return True, "Will verify the login when run."

    def available(self) -> tuple:
        from .. import creds
        if not creds.has_telethon_creds():
            return False, "Set api_id / api_hash in the Keys tab."
        try:
            from ...mtproto.client import build_client
        except Exception as exc:
            return False, f"Telethon import failed: {exc}"
        self._ensure_loop()
        try:
            client = build_client(self._config())
            client.connect()
            try:
                if not client.is_user_authorized():
                    return False, "Not logged in - use 'Log in' in the Keys tab."
            finally:
                client.disconnect()
        except Exception as exc:   # connection / loop issues
            return False, f"Telethon unavailable: {exc}"
        return True, ""

    def enrich(self, subject: Subject) -> EnrichmentResult:
        ok, why = self.available()
        if not ok:
            return EnrichmentResult(self.name, ok=False, error=why)
        from ...mtproto.client import build_client
        from ...mtproto import features
        target = subject.username or subject.user_id
        if target is None:
            return EnrichmentResult(self.name, ok=False, error="No username or id to resolve.")
        client = build_client(self._config())
        client.connect()
        try:
            findings: list = []
            info = features.resolve(client, target)
            name = info.get("first_name") or info.get("title") or info.get("username") or "?"
            findings.append(Finding(self.name, "profile",
                                    f"{name} - id {info.get('id')}"
                                    + (f" (@{info['username']})" if info.get("username") else ""),
                                    confidence="confirmed", detail=info))
            if info.get("phone"):
                findings.append(Finding(self.name, "profile", f"Phone: {info['phone']}",
                                        confidence="confirmed"))
            if info.get("scam"):
                findings.append(Finding(self.name, "flag", "Telegram flags this account as SCAM",
                                        confidence="confirmed"))
            if info.get("fake"):
                findings.append(Finding(self.name, "flag", "Telegram flags this account as FAKE",
                                        confidence="confirmed"))
            try:
                for chat in features.common_chats(client, target, limit=200):
                    nm = chat.get("title") or chat.get("username") or chat.get("id")
                    findings.append(Finding(self.name, "group", f"{nm} ({chat.get('kind')})",
                                            confidence="confirmed", detail=chat))
            except Exception as exc:
                findings.append(Finding(self.name, "lead", f"Common-groups lookup failed: {exc}"))
            return EnrichmentResult(self.name, findings=findings)
        except Exception as exc:
            return EnrichmentResult(self.name, ok=False, error=str(exc))
        finally:
            client.disconnect()


register(TelethonProvider())
