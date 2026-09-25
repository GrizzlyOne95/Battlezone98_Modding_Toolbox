"""GUI tests: embedding host, jobs and a shell smoke test over every page.

They need a display; CI runs them under xvfb. Without one they are skipped.
"""

import os
import tempfile
import time
import tkinter as tk
import tkinter.ttk  # noqa: F401 - tk.ttk in the shell test
import unittest
from pathlib import Path


def _make_root():
    try:
        return tk.Tk()
    except tk.TclError as exc:
        raise unittest.SkipTest(f"no display: {exc}")


def pump(root, seconds=0.3, until=None):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        if until is not None and until():
            return
        time.sleep(0.01)


class HostTests(unittest.TestCase):
    def setUp(self):
        self.root = _make_root()

    def tearDown(self):
        self.root.destroy()

    def test_embedded_root_accepts_toplevel_api(self):
        from bztoolbox.app.host import EmbeddedRoot

        container = tk.Frame(self.root)
        container.pack()
        host = EmbeddedRoot(container)
        host.pack()
        titles = []
        host.toolbox_on_title(titles.append)
        host.title("Legacy Tool")
        self.assertEqual(host.title(), "Legacy Tool")
        self.assertEqual(titles, ["Legacy Tool"])
        for call in (lambda: host.geometry("800x600"), lambda: host.minsize(10, 10),
                     lambda: host.iconbitmap("x.ico"), lambda: host.resizable(False, False),
                     lambda: host.configure(bg="#000000"), lambda: host.config(cursor="watch")):
            call()
        self.assertEqual(str(host.cget("bg")), "#000000")

    def test_close_handler_runs_on_shell_exit(self):
        from bztoolbox.app.host import EmbeddedRoot

        host = EmbeddedRoot(self.root)
        closed = []

        def on_close():
            closed.append(True)
            host.destroy()  # legacy tools destroy their "root" when closing

        host.protocol("WM_DELETE_WINDOW", on_close)
        host.toolbox_request_close()
        self.assertEqual(closed, [True])
        self.assertTrue(self.root.winfo_exists(), "closing a tool must not close the toolbox")

    def test_menubar_is_rendered_as_button_row(self):
        from bztoolbox.app.host import EmbeddedRoot

        container = tk.Frame(self.root)
        container.pack()
        host = EmbeddedRoot(container)
        host.pack()
        menubar = tk.Menu(host)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About")
        menubar.add_cascade(label="Help", menu=help_menu)
        host.config(menu=menubar)
        pump(self.root)
        bar = host._toolbox_menubar_frame
        self.assertIsNotNone(bar)
        self.assertEqual([w.cget("text") for w in bar.winfo_children()], ["Help"])

    def test_standalone_mode_creates_window(self):
        from bztoolbox.app.host import embeddable

        created = []

        def factory():
            top = tk.Toplevel(self.root)
            created.append(top)
            return top

        Standalone = embeddable(tk.Frame, factory)
        host = Standalone()
        host.title("Standalone")
        self.assertEqual(created[0].title(), "Standalone")
        host.destroy()
        self.assertFalse(created[0].winfo_exists())


class JobTests(unittest.TestCase):
    def setUp(self):
        self.root = _make_root()

    def tearDown(self):
        self.jobs.shutdown()
        self.root.destroy()

    def test_results_progress_and_errors_arrive_on_ui_thread(self):
        from bztoolbox.app.jobs import DONE, FAILED, JobManager

        self.jobs = JobManager(self.root, poll_ms=10)
        results, errors, updates = [], [], []
        self.jobs.add_listener(lambda job: updates.append((job.status, job.progress)) if job else None)

        def work(job):
            job.report(0.5, "half")
            return 42

        ok = self.jobs.submit("ok", work, on_done=results.append)
        bad = self.jobs.submit("bad", lambda job: 1 / 0, on_error=errors.append)
        pump(self.root, 3, until=lambda: results and errors)
        self.assertEqual(results, [42])
        self.assertEqual(ok.status, DONE)
        self.assertEqual(bad.status, FAILED)
        self.assertIn("ZeroDivisionError", errors[0])
        self.assertTrue(bad.details)
        # Progress updates are coalesced; the latest message survives.
        self.assertEqual(ok.message, "half")
        self.assertIn(("done", 1.0), updates)

    def test_cancel(self):
        from bztoolbox.app.jobs import CANCELLED, JobManager

        self.jobs = JobManager(self.root, poll_ms=10)

        def work(job):
            while True:
                job.check_cancelled()
                time.sleep(0.01)

        job = self.jobs.submit("loop", work)
        pump(self.root, 0.2)
        job.cancel()
        pump(self.root, 2, until=lambda: job.status == CANCELLED)
        self.assertEqual(job.status, CANCELLED)


class ShellSmokeTests(unittest.TestCase):
    def test_every_page_loads(self):
        root = _make_root()
        try:
            from bztoolbox.app.shell import Shell
            from bztoolbox.modules.registry import PAGES
            from bztoolbox.settings import Settings

            with tempfile.TemporaryDirectory() as tmp:
                mod = Path(tmp) / "mod"
                mod.mkdir()
                (mod / "mymod.ini").write_text('[WORKSHOP]\nmapType = "mod"\n')
                shell = Shell(root, Settings(Path(tmp) / "settings.json"))
                shell.open_project(str(mod))
                failures = []
                for page in PAGES:
                    shell.navigate(page.id)
                    pump(root, 0.2)
                    frame = shell._pages[page.id]
                    if frame.widget is None or not frame.widget.winfo_exists():
                        failures.append(page.id)
                self.assertEqual(failures, [])
                # The open project reached the migrated tools through their hooks.
                publish = shell._pages["project.publish"].app
                self.assertEqual(os.path.normpath(publish.mod_path.get()), str(mod))
                localization = shell._pages["project.localization"].app
                self.assertEqual(localization.scan_folder_path.get(), str(mod))

                # Native pages run their work on the job system.
                deps = shell._pages["project.dependencies"].widget
                deps.run()
                pump(root, 5, until=lambda: deps.graph is not None)
                self.assertEqual(deps.graph.summary()["files"], 1)
                self.assertEqual(len(deps.files.get_children()), 1)

                from battlezone.archives.zfs import write_zfs

                archive = Path(tmp) / "test.zfs"
                write_zfs(archive, [("unit.odf", b"[GameObjectClass]\n" * 50)], key="pw")
                zfs_page = shell._pages["archives.zfs"].widget
                zfs_page.open(str(archive))
                self.assertEqual(len(zfs_page.tree.get_children()), 1)

                # The update banner offers the right action and goes away again.
                from bztoolbox.updates import Update

                def banner_buttons():
                    return [w.cget("text") for w in shell._update_bar.winfo_children()
                            if isinstance(w, tk.ttk.Button)]

                shell.show_update(Update("99.0.0", "https://example.invalid/r",
                                         "https://example.invalid/s.exe", "BZModdingToolbox-v99.0.0-windows-setup.exe"))
                self.assertIn("Update now", banner_buttons())
                shell.show_update(Update("99.0.0", "https://example.invalid/r"))
                self.assertIn("Download", banner_buttons())
                self.assertEqual(len(shell.banner_slot.winfo_children()), 2)   # one bar + separator
                skip = next(w for w in shell._update_bar.winfo_children()
                            if isinstance(w, tk.ttk.Button) and w.cget("text") == "Skip this version")
                skip.invoke()
                self.assertEqual(shell.settings.get("update_skipped_version"), "99.0.0")
                self.assertEqual(shell.banner_slot.winfo_children(), [])
                shell.close(confirm=False)
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass


class ColumnResizeTests(unittest.TestCase):
    def test_dragged_stretch_column_keeps_its_width(self):
        root = _make_root()
        try:
            from bztoolbox.app.widgets import install_treeview_resize_cursor

            install_treeview_resize_cursor(root)
            root.geometry("600x300")
            tree = tk.ttk.Treeview(root, columns=("file", "kind", "size"), show="headings")
            for key, width, stretch in (("file", 300, True), ("kind", 100, False), ("size", 100, False)):
                tree.column(key, width=width, stretch=stretch)
            tree.pack(fill="both", expand=True)
            pump(root, 0.3)
            start = tree.column("file", "width")
            x = start   # the divider right of the stretch column
            self.assertEqual(tree.identify_region(x, 10), "separator")
            tree.event_generate("<ButtonPress-1>", x=x, y=10)
            for step in range(10, 110, 10):
                tree.event_generate("<B1-Motion>", x=x + step, y=10)
                pump(root, 0.02)
            tree.event_generate("<ButtonRelease-1>", x=x + 100, y=10)
            pump(root, 0.3)
            root.geometry("620x300")   # a relayout must not undo it either
            pump(root, 0.3)
            self.assertGreaterEqual(tree.column("file", "width"), start + 90)
        finally:
            root.destroy()


class ValidationFixTests(unittest.TestCase):
    def test_apply_fix_edits_the_file_and_revalidates(self):
        root = _make_root()
        try:
            from unittest import mock

            from bztoolbox.app.shell import Shell
            from bztoolbox.settings import Settings

            with tempfile.TemporaryDirectory() as tmp:
                mod = Path(tmp) / "mod"
                mod.mkdir()
                for name in ("a", "b"):
                    (mod / f"{name}.odf").write_text('[GameObjectClass]\nclassLabel = "wingman"\nfaction = "x"\n')
                shell = Shell(root, Settings(Path(tmp) / "settings.json"))
                shell.open_project(str(mod))
                shell.navigate("project.validation")
                page = shell._pages["project.validation"].widget
                pump(root, 10, until=lambda: page.report is not None)
                [first, *_] = [i for i in page.report.issues if i.fix]
                page._show_detail(first)
                self.assertEqual(str(page.fix_button.cget("state")), "normal")
                self.assertEqual(page.fix_all_button.cget("text"), "Fix all 2 like this")
                before = page.report
                with mock.patch("tkinter.messagebox.askokcancel", return_value=True):
                    page._apply_similar_fixes()
                self.assertEqual((mod / "a.odf").read_text(), '[GameObjectClass]\nclassLabel = "wingman"\nnation = "x"\n')
                self.assertIn("nation", (mod / "b.odf").read_text())
                pump(root, 10, until=lambda: page.report is not before)
                self.assertFalse([i for i in page.report.issues if i.fix])
                shell.close(confirm=False)
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass


class AutoRefreshTests(unittest.TestCase):
    def test_project_pages_rescan_when_shown_after_changes(self):
        root = _make_root()
        try:
            from bztoolbox.app.shell import Shell
            from bztoolbox.settings import Settings

            with tempfile.TemporaryDirectory() as tmp:
                mod = Path(tmp) / "mod"
                mod.mkdir()
                (mod / "a.odf").write_text("[GameObjectClass]\n")
                shell = Shell(root, Settings(Path(tmp) / "settings.json"))
                shell.open_project(str(mod))
                for page_id, attr in (("project.dependencies", "graph"), ("project.validation", "report")):
                    shell.navigate(page_id)
                    page = shell._pages[page_id].widget
                    pump(root, 10, until=lambda: getattr(page, attr) is not None)
                    first = getattr(page, attr)
                    self.assertIsNotNone(first, page_id)

                    shell.navigate("home")
                    shell.navigate(page_id)          # nothing changed: the result is kept
                    pump(root, 1, until=lambda: page.job.status == "done")
                    self.assertIs(getattr(page, attr), first)

                    (mod / f"{attr}.odf").write_text("[GameObjectClass]\n")
                    shell.navigate("home")
                    shell.navigate(page_id)          # a file was added: rescanned
                    pump(root, 10, until=lambda: getattr(page, attr) is not first)
                    self.assertIsNot(getattr(page, attr), first)

                other = Path(tmp) / "other"
                other.mkdir()
                shell.open_project(str(other))       # old results are not shown for a new mod
                deps = shell._pages["project.dependencies"].widget
                self.assertTrue(deps.graph is None or deps.graph.root == str(other))
                shell.close(confirm=False)
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass


if __name__ == "__main__":
    unittest.main()
