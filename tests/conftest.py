"""Keep every test away from the real per-user toolbox data directory."""

import os
import tempfile

import pytest

# Module-level paths computed at import time land in a session-wide temp dir...
os.environ["BZTOOLBOX_HOME"] = tempfile.mkdtemp(prefix="bztoolbox-test-home-")


@pytest.fixture(autouse=True)
def _isolated_toolbox_home(tmp_path, monkeypatch):
    # ...and everything resolved at run time (projects, settings) is per test.
    monkeypatch.setenv("BZTOOLBOX_HOME", str(tmp_path / "bztoolbox-home"))
