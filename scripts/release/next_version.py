"""Work out the version a merge to main releases as.

The CI workflow runs this on every build. Rules:

* The latest ``vX.Y.Z`` tag is the last release. The merged PR's labels pick
  the bump: ``release: major``, ``release: minor``, ``release: patch`` (the
  default) or ``release: skip`` (no release).
* A VERSION file newer than the latest tag wins as-is, so a maintainer can
  set the next version explicitly (and the first release is VERSION itself).
* A commit that already carries a release tag is not released again (a
  re-run of the workflow).

Prints ``key=value`` lines for $GITHUB_OUTPUT: version, tag, release, bump.

    python scripts/release/next_version.py --labels "release: minor,bug" \
        --tags "$(git tag -l 'v*')" --head-tags "$(git tag --points-at HEAD)"
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUMPS = ("major", "minor", "patch", "skip")
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse(value: str) -> tuple[int, int, int] | None:
    match = _VERSION.match(value.strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def bump_from_labels(labels) -> str:
    """The strongest ``release: ...`` label; skip beats everything, patch is the default."""
    found = set()
    for label in labels:
        match = re.fullmatch(r"release\s*:\s*(\w+)", label.strip(), re.IGNORECASE)
        if match and match.group(1).lower() in BUMPS:
            found.add(match.group(1).lower())
    for bump in ("skip", "major", "minor"):
        if bump in found:
            return bump
    return "patch"


def next_version(tags, version_file: str, bump: str) -> str:
    released = [v for v in (parse(tag) for tag in tags) if v]
    base = parse(version_file)
    if base is None:
        raise ValueError(f"VERSION must be X.Y.Z, not {version_file!r}")
    latest = max(released) if released else None
    if latest is None or base > latest:
        return "%d.%d.%d" % base
    major, minor, patch = latest
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def plan(tags, head_tags, version_file: str, labels) -> dict[str, str]:
    bump = bump_from_labels(labels)
    already = sorted((t for t in head_tags if parse(t)), key=parse)
    if already:
        version = "%d.%d.%d" % parse(already[-1])
        return {"version": version, "tag": f"v{version}", "release": "false", "bump": "already-released"}
    version = next_version(tags, version_file, bump)
    return {"version": version, "tag": f"v{version}", "release": "false" if bump == "skip" else "true",
            "bump": bump}


def _words(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n\r,]+", value or "") if item.strip()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", default="", help="comma- or newline-separated PR labels")
    parser.add_argument("--bump", choices=BUMPS, help="override the labels")
    parser.add_argument("--tags", default="", help="all tags, one per line")
    parser.add_argument("--head-tags", default="", help="tags on the commit being built")
    parser.add_argument("--version-file", type=Path, default=REPO_ROOT / "VERSION")
    args = parser.parse_args(argv)
    labels = [f"release: {args.bump}"] if args.bump else _words(args.labels)
    result = plan(args.tags.split(), args.head_tags.split(),
                  args.version_file.read_text(encoding="utf-8"), labels)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
