"""Capture every Toolbox page from a live Tk window for the README gallery.

Run on a Windows desktop with Pillow installed:
    python -m scripts.capture_toolbox_pages
Use --page PAGE_ID to capture a subset while reviewing layout.
"""
from __future__ import annotations

import argparse
import os
import tempfile
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path

from PIL import ImageGrab

from battlezone.project import ProjectStore
from bztoolbox.app.shell import Shell
from bztoolbox.modules.registry import PAGES, PAGES_BY_ID
from bztoolbox.settings import Settings


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def capture(pages: list[str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    public_temp = Path(os.environ.get("PUBLIC", tempfile.gettempdir())).resolve()
    with tempfile.TemporaryDirectory(prefix="bztoolbox-capture-", dir=public_temp) as scratch:
        base = Path(scratch).resolve()
        if not base.is_relative_to(public_temp):
            raise RuntimeError("Capture workspace escaped its temporary parent directory")
        previous_home = os.environ.get("BZTOOLBOX_HOME")
        os.environ["BZTOOLBOX_HOME"] = str(base / "toolbox-data")
        demo = base / "Example Mod"
        demo.mkdir()
        (demo / "mymod.ini").write_text('[WORKSHOP]\nmapType = "mod"\n', encoding="utf-8")
        (demo / "example.odf").write_text(
            '[GameObjectClass]\nclassLabel = "wingman"\n', encoding="utf-8")
        from battlezone.archives.pak import write_pak
        from battlezone.archives.zfs import write_zfs

        zfs_sample = base / "example.zfs"
        pak_sample = base / "example.pak"
        write_zfs(zfs_sample, [
            ("unit.odf", b'[GameObjectClass]\nclassLabel = "wingman"\n'),
            ("readme.txt", b"Example archive for Toolbox screenshots.\n"),
        ])
        write_pak(pak_sample, [
            ("ISDF Buildings", "example.pic", b"Example image member"),
            ("Effects", "spark.tga", b"Example effect member"),
        ])
        root = tk.Tk()
        shell = None
        try:
            # The publishing page normally probes the local Steam login and
            # credential store. A screenshot only needs its disconnected UI.
            from bztoolbox.modules.publishing.uploader import WorkshopUploader

            WorkshopUploader.load_config = lambda self: {}
            WorkshopUploader._load_api_key_from_secure_store = lambda self: None
            WorkshopUploader._save_api_key_to_secure_store = lambda self: None
            WorkshopUploader._bootstrap_steam_environment = lambda self: None
            WorkshopUploader._start_watch = lambda self: None
            WorkshopUploader.refresh_workshop_items = lambda self, quiet=False: None
            shell = Shell(root, Settings(base / "settings.json"))
            shell.projects = ProjectStore(base / "profiles")
            root.geometry("1500x950+80+80")
            root.attributes("-topmost", True)
            shell.open_project(str(demo))
            for page_id in pages:
                shell.navigate(page_id)
                deadline = time.monotonic() + 0.8
                while time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.04)
                frame = shell._pages[page_id]
                if frame.widget is None:
                    raise RuntimeError(f"Page failed to load: {page_id}")
                if page_id == "archives.zfs":
                    frame.widget.open(str(zfs_sample))
                elif page_id == "archives.pak":
                    frame.widget.open(str(pak_sample))
                elif page_id == "world.generate":
                    controls = list(descendants(frame.widget))
                    button = next(w for w in controls if isinstance(w, ttk.Button)
                                  and w.cget("text") == "GENERATE  (New Terrain)")
                    info = next(w for w in controls if isinstance(w, ttk.Label)
                                and w.cget("text") == "Generate a terrain to preview it.")
                    button.invoke()
                    deadline = time.monotonic() + 15
                    while "full generation" not in info.cget("text") and time.monotonic() < deadline:
                        root.update()
                        time.sleep(0.05)
                    if "full generation" not in info.cget("text"):
                        raise RuntimeError("Terrain preview did not finish")
                if page_id == "assets.holotext":
                    frame.app.output_dir.set(r"C:\Example Mod\HoloText")
                    frame.app.font_path.set("BZONE.ttf")
                    frame.app.lua_input.delete(0, "end")
                    frame.app.lua_input.insert(0, "EXAMPLE MOD")
                    frame.app.update_preview()
                elif page_id == "project.publish":
                    frame.app.username_var.set("")
                    frame.app.manage_identity_var.set("")
                    frame.app.owner_status_var.set("Workshop owner: not connected")
                    frame.app.api_key_status_var.set("API key: not configured")
                    frame.app.steam_login_status_var.set("Steam login: sign-in required")
                    frame.app.auth_detail_var.set("Connect a Steam account to publish.")
                root.update()
                time.sleep(0.1)
                root.update()
                image = ImageGrab.grab(window=root.winfo_id())
                filename = page_id.replace(".", "-") + ".png"
                image.save(output_dir / filename, optimize=True)
                print(f"{page_id}: {image.width}x{image.height} -> {filename}", flush=True)
        finally:
            if shell is not None:
                shell.jobs.shutdown()
            root.destroy()
            if previous_home is None:
                os.environ.pop("BZTOOLBOX_HOME", None)
            else:
                os.environ["BZTOOLBOX_HOME"] = previous_home


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", action="append", choices=list(PAGES_BY_ID),
                        help="page to capture; repeatable (default: every page)")
    parser.add_argument("--output-dir", type=Path,
                        default=Path("docs/images/toolbox-pages"))
    args = parser.parse_args()
    capture(args.page or [page.id for page in PAGES if page.available], args.output_dir)


if __name__ == "__main__":
    main()
