#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backward-compatible entry point.

The implementation moved into the ``telegram_tools`` package (shared with the
GUI). This shim keeps ``python telegram_tools_cli.py <command> ...`` working.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram_tools.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
