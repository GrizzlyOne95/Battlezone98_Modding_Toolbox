"""Frozen-executable entry point (a script, as PyInstaller expects)."""

import sys

from bztoolbox.cli import main

sys.exit(main())
