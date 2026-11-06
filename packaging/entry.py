"""Frozen-executable entry point (a script, as PyInstaller expects)."""

import multiprocessing
import sys

# Must run before anything else in a frozen build. Without it every
# ProcessPoolExecutor worker re-executes this script with the pool's
# "--multiprocessing-fork parent_pid=..." arguments, the CLI rejects them, and
# the pool dies with BrokenProcessPool (seen with `textures recompress --jobs`).
multiprocessing.freeze_support()

from bztoolbox.cli import main  # noqa: E402

sys.exit(main())
