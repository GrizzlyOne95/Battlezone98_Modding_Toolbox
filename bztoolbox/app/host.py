"""Host legacy tool windows inside the toolbox shell.

Each migrated tool was written as a top-level application: it receives (or
subclasses) a ``Tk`` root and calls window-manager methods on it such as
``title()``, ``geometry()``, ``protocol("WM_DELETE_WINDOW", ...)`` or
``config(menu=...)``. :func:`embeddable` builds a frame class that offers the
same API, so the tools can be mounted in a shell page without rewriting their
UI code:

* window-manager calls that only make sense for a top-level window become
  no-ops (or are forwarded to the real window when running standalone);
* the ``WM_DELETE_WINDOW`` handler is kept and called when the shell exits,
  so each tool still saves its settings;
* a menubar set with ``config(menu=...)`` is rendered as a button row above
  the tool.

The same classes also run a tool standalone: constructed without a master
they create their own top-level window, which keeps ``python -m`` entry points
of individual modules working during the migration.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

_NOOP_WM = (
    "minsize", "maxsize", "resizable", "iconbitmap", "iconphoto", "iconify", "deiconify",
    "withdraw", "state", "attributes", "overrideredirect", "wm_attributes", "wm_iconbitmap",
    "wm_iconphoto", "wm_state", "wm_minsize", "wm_maxsize", "wm_resizable", "positionfrom",
    "sizefrom", "transient", "wm_transient", "focusmodel", "aspect",
)


class _RootShim:
    """Mixin implementing the top-level window API on a frame."""

    _toolbox_standalone: Optional[tk.Misc] = None

    def _toolbox_init(self, standalone: Optional[tk.Misc], menubar_parent: Optional[tk.Misc]) -> None:
        self._toolbox_standalone = standalone
        self._toolbox_title = ""
        self._toolbox_close_handler: Optional[Callable[[], object]] = None
        self._toolbox_menubar_parent = menubar_parent
        self._toolbox_menubar_frame: Optional[tk.Frame] = None
        self._toolbox_menu: Optional[tk.Menu] = None
        self._toolbox_title_listeners: list = []

    # --- title / geometry -------------------------------------------------
    def title(self, text: Optional[str] = None):
        if text is None:
            return self._toolbox_title
        self._toolbox_title = str(text)
        if self._toolbox_standalone is not None:
            self._toolbox_standalone.title(text)
        for listener in list(self._toolbox_title_listeners):
            listener(self._toolbox_title)
        return ""

    wm_title = title

    def geometry(self, spec: Optional[str] = None):
        if self._toolbox_standalone is not None:
            return self._toolbox_standalone.geometry(spec) if spec else self._toolbox_standalone.geometry()
        if spec is None:
            self.update_idletasks()
            return f"{self.winfo_width()}x{self.winfo_height()}+0+0"
        return ""

    wm_geometry = geometry

    def protocol(self, name: Optional[str] = None, func: Optional[Callable] = None):
        if name == "WM_DELETE_WINDOW":
            if func is None:
                return self._toolbox_close_handler
            self._toolbox_close_handler = func
            if self._toolbox_standalone is not None:
                self._toolbox_standalone.protocol(name, func)
            return ""
        if self._toolbox_standalone is not None:
            return self._toolbox_standalone.protocol(name, func)
        return ""

    wm_protocol = protocol

    def mainloop(self, n: int = 0):
        if self._toolbox_standalone is not None:
            self._toolbox_standalone.mainloop(n)

    def quit(self):
        if self._toolbox_standalone is not None:
            self._toolbox_standalone.quit()

    def destroy(self):
        standalone = self._toolbox_standalone
        if standalone is not None:
            self._toolbox_standalone = None
            standalone.destroy()
            return
        if self._toolbox_menubar_frame is not None:
            try:
                self._toolbox_menubar_frame.destroy()
            except tk.TclError:
                pass
        super().destroy()  # type: ignore[misc]

    # --- menubar ----------------------------------------------------------
    def _toolbox_split_menu(self, args, kw):
        if args and isinstance(args[0], dict) and "menu" in args[0]:
            cnf = dict(args[0])
            kw = {**kw, "menu": cnf.pop("menu")}
            args = (cnf,) + tuple(args[1:])
        menu = kw.pop("menu", None)
        if menu is not None:
            self._toolbox_menu = menu
            self.after_idle(self._toolbox_render_menubar)
        return args, kw

    def _toolbox_render_menubar(self) -> None:
        menu = self._toolbox_menu
        parent = self._toolbox_menubar_parent or self._toolbox_standalone
        if menu is None or parent is None:
            return
        if self._toolbox_menubar_frame is not None:
            self._toolbox_menubar_frame.destroy()
        from bztoolbox.app import theme

        bar = tk.Frame(parent, bg=theme.SURFACE, highlightthickness=0)
        self._toolbox_menubar_frame = bar
        try:
            last = menu.index("end")
        except tk.TclError:
            last = None
        for index in range(0, (last if last is not None else -1) + 1):
            try:
                kind = menu.type(index)
            except tk.TclError:
                continue
            if kind not in ("cascade", "command"):
                continue
            label = menu.entrycget(index, "label")
            button = tk.Label(bar, text=label, bg=theme.SURFACE, fg=theme.FG, padx=10, pady=3,
                              cursor="hand2", font=theme.font("body", 9))
            button.pack(side="left")
            if kind == "cascade":
                submenu = self.nametowidget(menu.entrycget(index, "menu"))
                button.bind("<Button-1>", lambda e, m=submenu, b=button: m.tk_popup(
                    b.winfo_rootx(), b.winfo_rooty() + b.winfo_height()))
            else:
                button.bind("<Button-1>", lambda e, i=index: menu.invoke(i))
            button.bind("<Enter>", lambda e, b=button: b.configure(fg=theme.ACCENT))
            button.bind("<Leave>", lambda e, b=button: b.configure(fg=theme.FG))
        bar.pack(side="top", fill="x", before=self)  # type: ignore[call-arg]

    # --- shell integration -------------------------------------------------
    def toolbox_request_close(self) -> None:
        """Run the tool's own close handler (it usually saves settings)."""
        handler = self._toolbox_close_handler
        self._toolbox_close_handler = None
        if handler is not None:
            handler()

    def toolbox_on_title(self, listener: Callable[[str], None]) -> None:
        self._toolbox_title_listeners.append(listener)


def _wm_passthrough(name: str):
    def method(self, *args, **kwargs):
        standalone = self._toolbox_standalone
        if standalone is not None and hasattr(standalone, name):
            return getattr(standalone, name)(*args, **kwargs)
        return ""
    method.__name__ = name
    return method


for _name in _NOOP_WM:
    setattr(_RootShim, _name, _wm_passthrough(_name))


def embeddable(frame_cls, standalone_factory: Callable[[], tk.Misc]):
    """Build a root-compatible frame class on top of ``frame_cls``."""

    class EmbeddedRoot(_RootShim, frame_cls):  # type: ignore[misc, valid-type]
        def __init__(self, master: Optional[tk.Misc] = None, menubar_parent: Optional[tk.Misc] = None, **kw):
            standalone = None
            if master is None:
                standalone = standalone_factory()
                master = standalone
            frame_cls.__init__(self, master, **kw)
            self._toolbox_init(standalone, menubar_parent if menubar_parent is not None else master)
            if standalone is not None:
                self.pack(fill="both", expand=True)

        def configure(self, *args, **kw):
            args, kw = self._toolbox_split_menu(args, kw)
            if not args and not kw:
                return None
            return frame_cls.configure(self, *args, **kw)

        config = configure

    EmbeddedRoot.__name__ = f"Embedded{frame_cls.__name__}"
    EmbeddedRoot.__qualname__ = EmbeddedRoot.__name__
    return EmbeddedRoot


def _tk_root() -> tk.Tk:
    try:
        from tkinterdnd2 import TkinterDnD  # type: ignore

        return TkinterDnD.Tk()
    except Exception:
        return tk.Tk()


EmbeddedRoot = embeddable(tk.Frame, _tk_root)


_CTK_ROOT = None


def ctk_embedded_root():
    """Embeddable ``CTkFrame`` for tools built on customtkinter's ``CTk``."""
    global _CTK_ROOT
    if _CTK_ROOT is None:
        import customtkinter as ctk

        _CTK_ROOT = embeddable(ctk.CTkFrame, ctk.CTk)
    return _CTK_ROOT
