#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI entry point.

The implementation moved into the ``telegram_tools`` package (PyQt6, calling the
shared core in-process - no more subprocess). This shim launches it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram_tools.gui import run

if __name__ == "__main__":
    raise SystemExit(run())
