"""Translate the BZCC to Redux port form into :mod:`battlezone.bzn.bzcc_port` arguments.

Shared by the toolbox page and the standalone BZN Toolbox window.
"""

from __future__ import annotations


def build_port_arguments(fields, flags):
    """Translate the conversion form into the converter's CLI arguments."""
    values = {key: value.strip() for key, value in fields.items()}
    for key, label in (("source", "BZCC source BZN"),
                       ("template", "Redux template BZN"),
                       ("output", "output Redux BZN")):
        if not values.get(key):
            raise ValueError(f"Select a {label}.")
    args = [values["source"], values["template"], values["output"]]
    for key, option in (("mapping", "--map"), ("team_map", "--team-map"),
                        ("offset_from", "--offset-from"), ("report", "--report"),
                        ("terrain", "--terrain"), ("mission", "--mission")):
        if values.get(key):
            args.extend((option, values[key]))

    offset = [values.get(key, "") for key in ("offset_x", "offset_y", "offset_z")]
    if any(offset):
        if not all(offset):
            raise ValueError("Enter all three manual offset values (X, Y, Z).")
        if values.get("offset_from"):
            raise ValueError("Choose a terrain report or a manual offset, not both.")
        try:
            for value in offset:
                float(value)
        except ValueError as exc:
            raise ValueError("Manual offset values must be numbers.") from exc
        args.extend(("--offset", *offset))

    for key, option in (("source_odfs", "--source-odfs"),
                        ("redux_odfs", "--redux-odfs")):
        for directory in values.get(key, "").split(";"):
            if directory.strip():
                args.extend((option, directory.strip()))
    for key, option in (("allow_skips", "--allow-skips"),
                        ("auto_map", "--auto-map"),
                        ("allow_approximate", "--allow-approximate"),
                        ("allow_unsafe_classes", "--allow-unsafe-classes")):
        if flags.get(key):
            args.append(option)
    return args
