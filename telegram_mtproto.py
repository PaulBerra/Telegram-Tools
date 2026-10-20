#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry point for the MTProto advanced-mode CLI (user account via Telethon).

    python telegram_mtproto.py login --api-id <ID> --api-hash <HASH> --phone +33...
    python telegram_mtproto.py members @group --limit 500 --json
    python telegram_mtproto.py history @group --limit 1000 -o hist.ndjson
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram_tools.mtproto.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
