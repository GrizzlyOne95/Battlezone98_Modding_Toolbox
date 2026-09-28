"""Project > Test in Game: deploy the project, launch a mission with chosen options, read the logs."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from bztoolbox.app.widgets import Card, LogView, ScrollableFrame
from bztoolbox import launch

POLL_MS = 2000


class TestLaunchPage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        self.process = None
        self.watch = None
        saved = self._saved()
        self.installs = launch.detect_installs(shell.settings)
        extra_dir = saved.get("install", "")
        if extra_dir and not any(self._same(i.path, extra_dir) for i in self.installs):
            other = launch.install_at(extra_dir)
            if other:
                self.installs.append(other)
        self.install_var = tk.StringVar()
        self.mission = tk.StringVar(value=saved.get("mission", ""))
        self.extra = tk.StringVar(value=saved.get("extra", ""))
        self.deploy = tk.BooleanVar(value=saved.get("deploy", True))
        self.deploy_name = tk.StringVar()
        self.via_steam = tk.BooleanVar(value=saved.get("via_steam", False))
        self.flag_vars: dict = {}
        self._saved_flags = set(saved.get("flags", ["win", "nointro"]))

        body = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        body.pack(fill="both", expand=True)
        card = Card(body, "Test in game", "Copies the project into the game's addon folder (only changed files), "
                                         "starts a mission straight from the command line and, when the game "
                                         "closes, shows the problems the run wrote to the game's logs.")
        card.pack(fill="x", pady=(0, 12))
        form = card.body

        row = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Game", style="Toolbox.Surface.TLabel", width=18).pack(side="left")
        self.install_box = ttk.Combobox(row, textvariable=self.install_var, state="readonly",
                                        style="Toolbox.TCombobox")
        self.install_box.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.install_box.bind("<<ComboboxSelected>>", lambda _e: self._install_changed())
        ttk.Button(row, text="Other…", style="Toolbox.TButton", command=self._browse_install).pack(side="left")

        row = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Mission", style="Toolbox.Surface.TLabel", width=18).pack(side="left")
        self.mission_box = ttk.Combobox(row, textvariable=self.mission, style="Toolbox.TCombobox")
        self.mission_box.pack(side="left", fill="x", expand=True)
        ttk.Label(form, text="A .bzn from the project, or any mission name the game can find (misn05.bzn). "
                             "Empty: the game starts at its menu.",
                  style="Toolbox.SurfaceMuted.TLabel", wraplength=900, justify="left").pack(anchor="w")

        ttk.Label(form, text="Options", style="Toolbox.CardTitle.TLabel").pack(anchor="w", pady=(8, 2))
        self.flags_frame = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        self.flags_frame.pack(fill="x")
        row = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        row.pack(fill="x", pady=(4, 2))
        ttk.Label(row, text="Extra arguments", style="Toolbox.Surface.TLabel", width=18).pack(side="left")
        ttk.Entry(row, textvariable=self.extra, style="Toolbox.TEntry").pack(side="left", fill="x", expand=True)
        self.steam_check = ttk.Checkbutton(form, text="Launch through Steam (steam.exe -applaunch)",
                                           variable=self.via_steam, style="Toolbox.Surface.TCheckbutton",
                                           command=self._refresh_command)
        self.steam_check.pack(anchor="w")

        ttk.Label(form, text="Deploy", style="Toolbox.CardTitle.TLabel").pack(anchor="w", pady=(8, 2))
        row = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Checkbutton(row, text="Copy the project into addon\\", variable=self.deploy,
                        style="Toolbox.Surface.TCheckbutton", command=self._refresh_command).pack(side="left")
        ttk.Entry(row, textvariable=self.deploy_name, style="Toolbox.TEntry", width=28).pack(side="left", padx=(4, 6))
        ttk.Button(row, text="Remove deployed copy", style="Toolbox.TButton",
                   command=self._remove_deployment).pack(side="left")

        ttk.Label(form, text="Command", style="Toolbox.CardTitle.TLabel").pack(anchor="w", pady=(8, 2))
        self.command_label = ttk.Label(form, text="", style="Toolbox.SurfaceMuted.TLabel", wraplength=900,
                                       justify="left")
        self.command_label.pack(anchor="w")

        actions = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        actions.pack(fill="x", pady=(10, 0))
        self.launch_button = ttk.Button(actions, text="Launch", style="Toolbox.Accent.TButton", command=self.launch)
        self.launch_button.pack(side="left")
        ttk.Button(actions, text="Read logs now", style="Toolbox.TButton", command=self._collect).pack(
            side="left", padx=(8, 0))
        ttk.Button(actions, text="Open addon folder", style="Toolbox.TButton", command=self._open_addon).pack(
            side="left", padx=(8, 0))

        ttk.Label(body, text="RUN", style="Toolbox.Heading.TLabel").pack(anchor="w")
        self.log = LogView(body, height=16)
        self.log.pack(fill="both", expand=True, pady=(4, 0))

        for var in (self.mission, self.extra, self.deploy_name):
            var.trace_add("write", lambda *_: self._refresh_command())
        self._fill_installs(saved.get("install", ""))
        self.project_changed(shell.project)
        if not self.installs:
            self.log.write("No Battlezone install found. Use Other… to pick the game folder.", "warning")

    # --- state ------------------------------------------------------------------
    @staticmethod
    def _same(a, b) -> bool:
        return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))

    def _saved(self) -> dict:
        try:
            value = self.shell.settings.get("test_launch", {})
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _save(self) -> None:
        install = self._install()
        try:
            self.shell.settings.set("test_launch", {
                "install": str(install.path) if install else "", "mission": self.mission.get(),
                "extra": self.extra.get(), "deploy": self.deploy.get(), "via_steam": self.via_steam.get(),
                "flags": [key for key, var in self.flag_vars.items() if var.get()]})
        except Exception:
            pass

    def _install(self):
        labels = [i.label for i in self.installs]
        value = self.install_var.get()
        return self.installs[labels.index(value)] if value in labels else None

    def _fill_installs(self, preferred: str = "") -> None:
        self.install_box.configure(values=[i.label for i in self.installs])
        chosen = next((i for i in self.installs if preferred and self._same(i.path, preferred)), None)
        chosen = chosen or (self.installs[0] if self.installs else None)
        self.install_var.set(chosen.label if chosen else "")
        self._install_changed()

    def _install_changed(self) -> None:
        install = self._install()
        for child in self.flags_frame.winfo_children():
            child.destroy()
        previous = {key for key, var in self.flag_vars.items() if var.get()} or self._saved_flags
        self.flag_vars = {}
        if install is not None:
            for index, flag in enumerate(install.flags):
                var = tk.BooleanVar(value=flag.key in previous)
                self.flag_vars[flag.key] = var
                text = f"{flag.label}  ({flag.arg})"
                box = ttk.Checkbutton(self.flags_frame, text=text, variable=var, style="Toolbox.Surface.TCheckbutton",
                                      command=self._refresh_command)
                box.grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 18))
        steam_ok = install is not None and install.kind == "redux" and install.store == "steam" and launch.steam_exe()
        self.steam_check.state(["!disabled"] if steam_ok else ["disabled"])
        if not steam_ok:
            self.via_steam.set(False)
        self._refresh_command()

    def _browse_install(self) -> None:
        folder = filedialog.askdirectory(title="Battlezone game folder (battlezone98redux.exe or bzone.exe)")
        if not folder:
            return
        install = launch.install_at(folder)
        if install is None:
            messagebox.showerror("Test in game", "No battlezone98redux.exe or bzone.exe in that folder.")
            return
        if not any(self._same(i.path, install.path) for i in self.installs):
            self.installs.append(install)
        self._fill_installs(str(install.path))

    def project_changed(self, project) -> None:
        folder = project.mod_path if project else ""
        missions = launch.missions_in(folder) if folder else []
        self.mission_box.configure(values=missions)
        if missions and self.mission.get() not in missions:
            self.mission.set(missions[0])
        self.deploy_name.set(launch.deploy_name(folder) if folder else "")
        self._refresh_command()

    def _plan(self):
        install = self._install()
        if install is None:
            raise ValueError("Choose a game install.")
        flags = [key for key, var in self.flag_vars.items() if var.get()]
        return install, launch.build_launch(install, self.mission.get(), flags, self.extra.get(),
                                            via_steam=self.via_steam.get())

    def _refresh_command(self) -> None:
        try:
            install, plan = self._plan()
            text = plan.command_line()
            if self.deploy.get() and self.shell.project and self.deploy_name.get().strip():
                text = f"(copy the project to {install.addon / self.deploy_name.get().strip()} first)\n" + text
        except (ValueError, FileNotFoundError, OSError) as exc:
            text = str(exc)
        self.command_label.configure(text=text)

    # --- actions ----------------------------------------------------------------
    def launch(self) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showinfo("Test in game", "The game from the last launch is still running.")
            return
        try:
            install, plan = self._plan()
        except (ValueError, FileNotFoundError, OSError) as exc:
            messagebox.showerror("Test in game", str(exc))
            return
        self.log.clear()
        project = self.shell.project
        if self.deploy.get() and project is not None:
            name = self.deploy_name.get().strip()
            if not name:
                messagebox.showerror("Test in game", "Give the addon folder a name, or turn off deploying.")
                return
            try:
                result = launch.deploy_project(project.mod_path, install, name)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Test in game", f"Deploy failed: {exc}")
                return
            self.log.write(f"Deployed to {result.target}: {len(result.copied)} copied, {result.unchanged} unchanged"
                           + (f", {len(result.skipped)} editor files skipped" if result.skipped else ""), "info")
        self._save()
        self.watch = launch.LogWatch(install)
        try:
            self.process = launch.start(plan)
        except OSError as exc:
            self.log.write(f"Could not start the game: {exc}", "error")
            return
        self.log.write(f"Started: {plan.command_line()}", "info")
        if plan.via_steam:
            self.log.write("Started through Steam: the game runs outside this process; press Read logs now "
                           "when you are done.", "muted")
            self.process = None
        else:
            self.shell.status("Game running…")
            self.after(POLL_MS, self._poll)

    def _poll(self) -> None:
        if self.process is None:
            return
        code = self.process.poll()
        if code is None:
            self.after(POLL_MS, self._poll)
            return
        self.process = None
        self.log.write(f"Game closed (exit code {code}).", "info" if code == 0 else "warning")
        self._collect()

    def _collect(self) -> None:
        if self.watch is None:
            install = self._install()
            if install is None:
                return
            self.log.write("No launch from this page yet: showing the last 200 lines of each log.", "muted")
            self.watch = launch.LogWatch(install)
            self.watch.offsets = {p: max(0, (p.stat().st_size if p.is_file() else 0) - 20000)
                                  for p in self.watch.offsets}
        found = self.watch.new_lines()
        if not found:
            self.log.write("The logs gained nothing since the launch.", "muted")
            return
        total = 0
        for name, lines in found.items():
            problems = launch.flagged(lines)
            total += len(problems)
            self.log.write(f"{name}: {len(lines)} new line(s), {len(problems)} look like problems",
                           "warning" if problems else "success")
            for line in problems[:200]:
                self.log.write("  " + line, "warning")
        self.shell.status(f"Game logs: {total} problem line(s)")

    def _remove_deployment(self) -> None:
        install, name = self._install(), self.deploy_name.get().strip()
        if install is None or not name:
            return
        target = install.addon / name
        if not target.is_dir():
            messagebox.showinfo("Test in game", f"Nothing deployed at {target}.")
            return
        if messagebox.askyesno("Remove deployed copy", f"Delete this folder?\n\n{target}"):
            launch.remove_deployment(install, name)
            self.log.write(f"Removed {target}", "info")

    def _open_addon(self) -> None:
        install = self._install()
        if install is None:
            return
        install.addon.mkdir(exist_ok=True)
        os.startfile(install.addon) if hasattr(os, "startfile") else None
