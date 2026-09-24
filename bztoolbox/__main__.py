"""``python -m bztoolbox`` and the frozen executable entry point."""

import sys

from bztoolbox.cli import main

if __name__ == "__main__":
    sys.exit(main())
