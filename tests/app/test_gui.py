"""GUI tests: embedding host, jobs and a shell smoke test over every page.

They need a display; CI runs them under xvfb. Without one they are skipped.
"""

import os
import tempfile
import time
import tkinter as tk
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
                    if frame.widget is None:
                        failures.append(page.id)
                self.assertEqual(failures, [])
                # The open project reached the migrated tools through their hooks.
                publish = shell._pages["project.publish"].app
                self.assertEqual(os.path.normpath(publish.mod_path.get()), str(mod))
                localization = shell._pages["project.localization"].app
                self.assertEqual(localization.scan_folder_path.get(), str(mod))
                shell.close(confirm=False)
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass


if __name__ == "__main__":
    unittest.main()
