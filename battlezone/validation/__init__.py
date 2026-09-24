"""One validation engine for Battlezone mod projects.

Before consolidation the Workshop Uploader and the BZN Toolbox each carried
their own checks and could disagree about the same mod. This package is the
single source of truth: mission inspection, the project validation page, the
``bztoolbox validate`` command and the publishing preflight all run the same
checks and report the same :class:`Issue` records.
"""

from battlezone.validation.engine import (
    CHECKS,
    DEFAULT_CHECKS,
    Check,
    Issue,
    ValidationCancelled,
    ValidationReport,
    validate_project,
)

__all__ = [
    "CHECKS",
    "DEFAULT_CHECKS",
    "Check",
    "Issue",
    "ValidationCancelled",
    "ValidationReport",
    "validate_project",
]
