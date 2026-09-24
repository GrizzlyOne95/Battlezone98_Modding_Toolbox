"""Find the textures a mod draws as UI, so a batch recompress can leave them alone.

Block compression is a good trade almost everywhere, but not on art that is
drawn at 1:1 with hard edges. BC1 quantises each 4x4 block to two endpoints and
two interpolated steps, which on a glyph edge or a thin HUD rule shows up as
ringing rather than as the slight desaturation it causes on a diffuse map -- and
these are the pixels a player looks at for the whole mission.

In Redux this is legible from the material scheme rather than from the file
name: BZSprite/AlphaHUD and BZSprite/AlphaHUDPixel are the 2D overlay passes,
and "Pixel" is the point-sampled one. In ISDF Chronicles that set is bzfont,
numbers2, IsdfHUD, evhud, pings and the three weapon reticles -- about 39 MB
against the 6.4 GB of uncompressed art, so skipping them costs 0.6% of the
saving and removes the whole class of visible risk.

Deliberately conservative: this matches on the scheme a material inherits, so a
texture that is *also* used on a world model is still skipped. The saving lost
is not worth the analysis.
"""
import os
import re
import glob

# Only the 2D overlay passes. Matched on the inherited scheme, not on the
# material name: BZBaseCockpit is a world-space model that happens to be drawn
# close to the camera, not an overlay, and has no business on this list.
UI_SCHEME = re.compile(r"(^|/)(Alpha)?HUD|/UI(/|$)|Font", re.I)
_DECL = re.compile(r"^[ \t]*material\s+(\S+)\s*:\s*(\S+)[^\n{]*", re.M)


def _block(txt, start):
    """Return the brace-balanced body beginning at or after `start`, and its end.

    A plain non-greedy `.*?\\n\\}` stops at the first line-leading brace, which in
    these files is often the end of a nested texture_unit -- so the captured body
    runs on into the following material and attributes its textures to the wrong
    scheme. That is how a cockpit model first showed up as UI here.
    """
    i = txt.find("{", start)
    if i < 0:
        return "", len(txt)
    depth, j = 0, i
    while j < len(txt):
        if txt[j] == "{":
            depth += 1
        elif txt[j] == "}":
            depth -= 1
            if depth == 0:
                return txt[i + 1:j], j
        j += 1
    return txt[i + 1:], len(txt)


def ui_textures(folder):
    """-> {lowercased dds basename: the material scheme that made it UI}."""
    found = {}
    for path in glob.glob(os.path.join(folder, "*.material")):
        try:
            txt = open(path, errors="replace").read()
        except OSError:
            continue
        for m in _DECL.finditer(txt):
            name, parent = m.group(1), m.group(2)
            body, _ = _block(txt, m.end())
            if not UI_SCHEME.search(parent):
                continue
            for tex in re.findall(r"set_texture_alias\s+\w+\s+(\S+\.dds)", body, re.I):
                found.setdefault(tex.lower(), parent)
    return found


if __name__ == "__main__":
    import sys
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    hits = ui_textures(folder)
    total = 0
    for tex, scheme in sorted(hits.items()):
        p = os.path.join(folder, tex)
        size = os.path.getsize(p) if os.path.exists(p) else 0
        total += size
        print("  %-28s %-24s %8.2f MB%s" % (
            tex, scheme, size / 1048576, "" if size else "   (not present)"))
    print("\n%d UI textures, %.1f MB" % (len(hits), total / 1048576))
