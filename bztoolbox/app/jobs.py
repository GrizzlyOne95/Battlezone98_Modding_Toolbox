"""One background task system for the whole toolbox.

Work runs on a small thread pool; everything the UI sees (progress, status,
completion callbacks) is marshalled back onto the Tk thread by polling a
queue, so job functions never touch widgets directly::

    def work(job):
        for i, item in enumerate(items):
            job.check_cancelled()
            job.report(i / len(items), f"Processing {item}")
        return result

    jobs.submit("Validate project", work, on_done=show_report)
"""

from __future__ import annotations

import itertools
import queue
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"
FINISHED = (DONE, FAILED, CANCELLED)


class JobCancelled(Exception):
    pass


@dataclass
class Job:
    id: int
    title: str
    status: str = QUEUED
    progress: Optional[float] = None       # 0..1, or None when indeterminate
    message: str = ""
    result: Any = None
    error: str = ""
    details: str = ""                      # traceback of a failed job
    started: float = 0.0
    finished: float = 0.0
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _manager: Optional["JobManager"] = field(default=None, repr=False)

    # --- called from the worker thread ------------------------------------
    def report(self, progress: Optional[float] = None, message: Optional[str] = None) -> None:
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        if message is not None:
            self.message = message
        if self._manager is not None:
            self._manager._post(self)

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled()

    # --- called from the UI thread ----------------------------------------
    def cancel(self) -> None:
        self.cancel_event.set()
        if self._manager is not None:
            self._manager._post(self)

    @property
    def elapsed(self) -> float:
        if not self.started:
            return 0.0
        return (self.finished or time.monotonic()) - self.started


class JobManager:
    def __init__(self, tk_root, max_workers: int = 3, poll_ms: int = 80):
        self._root = tk_root
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="bztoolbox-job")
        self._events: "queue.Queue[tuple[Job, Optional[Callable]]]" = queue.Queue()
        self._ids = itertools.count(1)
        self._listeners: List[Callable[[Job], None]] = []
        self._poll_ms = poll_ms
        self.jobs: List[Job] = []
        self._closed = False
        self._after_id = self._root.after(self._poll_ms, self._drain)

    def add_listener(self, callback: Callable[[Job], None]) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[Job], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    @property
    def active(self) -> List[Job]:
        return [job for job in self.jobs if job.status not in FINISHED]

    def submit(
        self,
        title: str,
        func: Callable[[Job], Any],
        on_done: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> Job:
        job = Job(next(self._ids), title, _manager=self)
        self.jobs.append(job)
        self._post(job)

        def run() -> None:
            job.status = RUNNING
            job.started = time.monotonic()
            self._post(job)
            callback = None
            try:
                job.check_cancelled()
                job.result = func(job)
                job.status = DONE
                if job.progress is not None:
                    job.progress = 1.0
                if on_done is not None:
                    callback = lambda: on_done(job.result)
            except JobCancelled:
                job.status = CANCELLED
                job.message = "Cancelled"
            except Exception as exc:  # noqa: BLE001 - report every failure to the UI
                if job.cancelled:
                    job.status, job.message = CANCELLED, "Cancelled"
                else:
                    job.status = FAILED
                    job.error = f"{exc.__class__.__name__}: {exc}"
                    job.message = str(exc) or job.error
                    job.details = traceback.format_exc()
                    if on_error is not None:
                        callback = lambda: on_error(job.error)
            finally:
                job.finished = time.monotonic()
                self._post(job, callback)

        self._executor.submit(run)
        return job

    def clear_finished(self) -> None:
        self.jobs = [job for job in self.jobs if job.status not in FINISHED]
        for listener in list(self._listeners):
            listener(None)  # type: ignore[arg-type]

    def shutdown(self) -> None:
        self._closed = True
        try:
            self._root.after_cancel(self._after_id)
        except Exception:  # noqa: BLE001 - root may already be gone
            pass
        for job in self.active:
            job.cancel_event.set()
        self._executor.shutdown(wait=False, cancel_futures=True)

    # --- internals ----------------------------------------------------------
    def _post(self, job: Job, callback: Optional[Callable] = None) -> None:
        self._events.put((job, callback))

    def _drain(self) -> None:
        if self._closed:
            return
        changed = {}
        callbacks = []
        try:
            while True:
                job, callback = self._events.get_nowait()
                changed[job.id] = job
                if callback is not None:
                    callbacks.append(callback)
        except queue.Empty:
            pass
        for job in changed.values():
            for listener in list(self._listeners):
                try:
                    listener(job)
                except Exception:  # noqa: BLE001 - a broken listener must not stop polling
                    traceback.print_exc()
        for callback in callbacks:
            try:
                callback()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        try:
            self._after_id = self._root.after(self._poll_ms, self._drain)
        except Exception:  # root destroyed
            self._closed = True
