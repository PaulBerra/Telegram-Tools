"""Local, opt-in credentials for deeper enrichment (Telethon + API keys).

Stored in ~/.telegram_tools/credentials.json (gitignored via .telegram_tools/).
Nothing here imports Telethon; it is just a small typed key/value store so the
GUI and the enrichment providers agree on where the secrets live.
"""

from __future__ import annotations

import json
import os

DIR = os.path.join(os.path.expanduser("~"), ".telegram_tools")
_CREDS = os.path.join(DIR, "credentials.json")
# The MTProto session file lives next to the creds (it AUTHORIZES the account).
SESSION = os.path.join(DIR, "mtproto.session")

FIELDS = ("tg_api_id", "tg_api_hash", "tg_phone", "tgstat_key")


def load_credentials() -> dict:
    out = {k: "" for k in FIELDS}
    try:
        with open(_CREDS, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            for k in FIELDS:
                if data.get(k) is not None:
                    out[k] = str(data[k])
    except (OSError, ValueError):
        pass
    return out


def save_credentials(values: dict) -> None:
    cur = load_credentials()
    for k in FIELDS:
        if k in values:
            cur[k] = str(values[k]).strip()
    try:
        os.makedirs(DIR, exist_ok=True)
        with open(_CREDS, "w", encoding="utf-8") as fh:
            json.dump(cur, fh, indent=2)
    except OSError:
        pass


def has_telethon_creds() -> bool:
    c = load_credentials()
    return bool(c.get("tg_api_id") and c.get("tg_api_hash"))
