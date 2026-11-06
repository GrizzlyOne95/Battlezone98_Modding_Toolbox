"""Prepare one set of GitHub-generated release notes for every distribution.

GitHub's generated Markdown is also the published release body. Inno Setup's
InfoBeforeFile expects plain text, so it receives a readable text equivalent.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def prepare_notes(version: str, body: str) -> tuple[str, str]:
    version = version.strip()
    body = body.strip()
    if not version or not body or body.lower() == "null":
        raise ValueError("a release version and nonempty notes are required")

    markdown = f"# Battlezone Modding Toolbox {version}\n\n{body}\n"
    plain = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", markdown)
    plain = re.sub(r"(?m)^#{1,6}\s+(.+)$", lambda m: m.group(1).upper(), plain)
    plain = re.sub(r"(?m)^\s*[*+]\s+", "- ", plain)
    plain = re.sub(r"\*\*(.*?)\*\*", r"\1", plain)
    plain = re.sub(r"`([^`]+)`", r"\1", plain)
    return markdown, plain.rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--body", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--text", type=Path, required=True)
    args = parser.parse_args()

    markdown, plain = prepare_notes(args.version, args.body.read_text(encoding="utf-8"))
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.text.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(markdown, encoding="utf-8")
    # A BOM makes the Inno Setup information page identify UTF-8 correctly.
    args.text.write_text(plain, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
