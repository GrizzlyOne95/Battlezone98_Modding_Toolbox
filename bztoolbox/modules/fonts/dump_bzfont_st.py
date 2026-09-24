import argparse
import json
import re
from pathlib import Path

SPRITE_RE = re.compile(
    r'^"char\.(?P<code>\d+)"\s+\S+\s+'
    r'(?P<u>\d+)\s+(?P<v>\d+)\s+(?P<w>\d+)\s+(?P<h>\d+)\s+'
    r'(?P<ref_w>\d+)\s+(?P<ref_h>\d+)\s+(?P<flags>0x[0-9A-Fa-f]+)$'
)


def parse_bzfont_st(st_path):
    entries = {}
    for raw_line in Path(st_path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        match = SPRITE_RE.match(line)
        if not match:
            continue

        code = int(match.group("code"))
        entries[code] = {
            "code": code,
            "char": chr(code) if 32 <= code <= 126 else "",
            "u": int(match.group("u")),
            "v": int(match.group("v")),
            "w": int(match.group("w")),
            "h": int(match.group("h")),
            "ref_w": int(match.group("ref_w")),
            "ref_h": int(match.group("ref_h")),
            "flags": match.group("flags"),
        }
    return entries


def main():
    parser = argparse.ArgumentParser(description="Dump stock Battlezone font sprite coordinates from bzfont.st.")
    parser.add_argument("st_path", help="Path to Edit\\stock\\bzfont.st")
    parser.add_argument("--start", type=int, default=32, help="First character code to include")
    parser.add_argument("--end", type=int, default=126, help="Last character code to include")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    entries = parse_bzfont_st(args.st_path)
    filtered = {code: data for code, data in entries.items() if args.start <= code <= args.end}
    dump = json.dumps(filtered, indent=2 if args.pretty else None, sort_keys=True)
    print(dump)


if __name__ == "__main__":
    main()
