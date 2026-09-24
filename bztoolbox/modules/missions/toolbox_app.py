import contextlib
import io
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from battlezone.bzn.bzcc_port import main as bzcc_port_main
from bztoolbox.modules.missions.bzn_scan import BZNParser, STOCK_SET
from battlezone.odf.evidence import resolve_evidence
from battlezone.odf.validator import validate_directory, validate_zip


APP_USER_MODEL_ID = "GrizzlyOne95.Battlezone98Redux.BZNToolbox"


def _set_app_user_model_id():
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def _resolve_bundled_icon(name):
    """Locate a bundled icon working from source and under sys._MEIPASS."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "branding", name))
        candidates.append(os.path.join(meipass, name))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "branding", name))
    candidates.append(os.path.join(here, name))
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def apply_window_icon(window):
    """Apply the canonical (BZNTools) app icon to a Tk/Toplevel window."""
    try:
        ico_path = _resolve_bundled_icon("app_icon.ico")
        if ico_path:
            try:
                window.iconbitmap(ico_path)
            except Exception:
                pass
        png_path = _resolve_bundled_icon("app_icon.png")
        if png_path:
            try:
                image = tk.PhotoImage(file=png_path)
                window.iconphoto(True, image)
                window._battlezone_app_icon = image
            except Exception:
                pass
    except Exception:
        pass


_set_app_user_model_id()


SEVERITY_ORDER = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3}


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


class BZNToolboxApp:
    def __init__(self, root):
        self.root = root
        apply_window_icon(self.root)
        self.root.title("Battlezone BZN Toolbox")
        self.root.geometry("1280x760")

        self.current_file = None
        self.source_kind = None  # bzn | folder | zip
        self.source_path = None
        self.dependency_data = []
        self.issue_data = []
        self.issue_lookup = {}

        controls = tk.Frame(root)
        controls.pack(pady=(10, 4), padx=10, fill=tk.X)

        tk.Button(controls, text="Load BZN", command=self.load_file).pack(side=tk.LEFT)
        tk.Button(controls, text="Scan ODF Folder", command=self.load_folder).pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(controls, text="Scan ZIP", command=self.load_zip).pack(side=tk.LEFT, padx=(8, 0))

        self.custom_only = tk.BooleanVar(value=False)
        tk.Checkbutton(
            controls,
            text="Custom ODFs Only",
            variable=self.custom_only,
            command=self.refresh_dependencies,
        ).pack(side=tk.LEFT, padx=(18, 0))

        self.referenced_only = tk.BooleanVar(value=False)
        self.referenced_check = tk.Checkbutton(
            controls,
            text="Validate Referenced ODFs Only",
            variable=self.referenced_only,
            command=self.revalidate,
        )
        self.referenced_check.pack(side=tk.LEFT, padx=(12, 0))
        self.referenced_check.configure(state=tk.DISABLED)

        self.status_lbl = tk.Label(root, text="Load a BZN, ODF folder, or ZIP to begin", fg="gray", anchor="w")
        self.status_lbl.pack(padx=10, fill=tk.X)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.dependencies_tab = ttk.Frame(self.notebook)
        self.validation_tab = ttk.Frame(self.notebook)
        self.port_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.dependencies_tab, text="BZN Dependencies")
        self.notebook.add(self.validation_tab, text="ODF Validation")
        self.notebook.add(self.port_tab, text="BZCC to Redux Port")

        self._build_dependency_tab()
        self._build_validation_tab()
        self._build_port_tab()

    def _build_port_tab(self):
        self.port_fields = {key: tk.StringVar(value="LuaMission" if key == "mission" else "")
                            for key in ("source", "template", "output", "mapping", "team_map",
                                        "offset_from", "offset_x", "offset_y", "offset_z",
                                        "report", "terrain", "mission", "source_odfs", "redux_odfs")}
        self.port_flags = {key: tk.BooleanVar(value=False)
                           for key in ("allow_skips", "auto_map", "allow_approximate",
                                       "allow_unsafe_classes")}

        form = ttk.Frame(self.port_tab, padding=12)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)

        def file_row(row, label, key, kind="bzn", save=False):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(form, textvariable=self.port_fields[key]).grid(
                row=row, column=1, sticky="ew", padx=(10, 8), pady=3)
            ttk.Button(form, text="Browse...", command=lambda: self._browse_port_file(key, kind, save)).grid(
                row=row, column=2, sticky="ew", pady=3)

        file_row(0, "BZCC source BZN", "source")
        file_row(1, "Redux ASCII template", "template")
        file_row(2, "Output Redux BZN", "output", save=True)
        file_row(3, "ODF mapping JSON", "mapping", "json")
        file_row(4, "Team mapping JSON", "team_map", "json")
        file_row(5, "Terrain port report JSON", "offset_from", "json")
        file_row(6, "Conversion report JSON", "report", "json", save=True)

        for row, label, key in ((7, "Terrain name override", "terrain"),
                                (8, "Redux mission class", "mission")):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(form, textvariable=self.port_fields[key]).grid(
                row=row, column=1, sticky="ew", padx=(10, 8), pady=3)

        ttk.Label(form, text="Manual offset X / Y / Z").grid(row=9, column=0, sticky="w", pady=3)
        offset_frame = ttk.Frame(form)
        offset_frame.grid(row=9, column=1, sticky="w", padx=(10, 8), pady=3)
        for index, key in enumerate(("offset_x", "offset_y", "offset_z")):
            ttk.Entry(offset_frame, textvariable=self.port_fields[key], width=12).grid(
                row=0, column=index, padx=(0, 8))

        for row, label, key in ((10, "Source ODF folders (; separated)", "source_odfs"),
                                (11, "Redux ODF folders (; separated)", "redux_odfs")):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(form, textvariable=self.port_fields[key]).grid(
                row=row, column=1, sticky="ew", padx=(10, 8), pady=3)
            ttk.Button(form, text="Add folder...", command=lambda k=key: self._browse_port_folder(k)).grid(
                row=row, column=2, sticky="ew", pady=3)

        flags = ttk.Frame(form)
        flags.grid(row=12, column=0, columnspan=3, sticky="w", pady=(8, 4))
        for index, (key, label) in enumerate((("auto_map", "Auto-map classes"),
                                              ("allow_approximate", "Allow approximate classes"),
                                              ("allow_unsafe_classes", "Allow unsafe classes"),
                                              ("allow_skips", "Allow skipped objects"))):
            ttk.Checkbutton(flags, text=label, variable=self.port_flags[key]).grid(
                row=0, column=index, padx=(0, 15))

        ttk.Label(form, text="Use the terrain report from the same terrain build; teams outside 0–15 need a team map.",
                  foreground="gray").grid(row=13, column=0, columnspan=3, sticky="w", pady=(2, 8))
        actions = ttk.Frame(form)
        actions.grid(row=14, column=0, columnspan=3, sticky="w")
        ttk.Button(actions, text="Convert BZN", command=self.run_port).pack(side=tk.LEFT)
        ttk.Button(actions, text="Scan output", command=self.scan_port_output).pack(side=tk.LEFT, padx=(8, 0))
        self.port_result = tk.StringVar(value="Select a BZCC source and an ASCII Redux template to begin.")
        ttk.Label(form, textvariable=self.port_result, wraplength=1050, justify=tk.LEFT).grid(
            row=15, column=0, columnspan=3, sticky="ew", pady=(12, 0))

    def _browse_port_file(self, key, kind, save):
        filetypes = ([("BZN files", "*.bzn")] if kind == "bzn" else
                     [("JSON files", "*.json")])
        filetypes.append(("All files", "*.*"))
        current = self.port_fields[key].get().strip()
        initialdir = str(Path(current).parent) if current else ""
        picker = filedialog.asksaveasfilename if save else filedialog.askopenfilename
        options = {"title": "Select " + key.replace("_", " "),
                   "filetypes": filetypes, "defaultextension": "." + kind}
        if initialdir:
            options["initialdir"] = initialdir
        path = picker(**options)
        if path:
            self.port_fields[key].set(path)
            if key == "output" and not self.port_fields["report"].get().strip():
                self.port_fields["report"].set(str(Path(path).with_name(Path(path).stem + "_port_report.json")))

    def _browse_port_folder(self, key):
        path = filedialog.askdirectory(title="Add " + key.replace("_", " ") + " folder")
        if path:
            previous = self.port_fields[key].get().strip()
            self.port_fields[key].set(previous + ("; " if previous else "") + path)

    def run_port(self):
        try:
            fields = {key: value.get() for key, value in self.port_fields.items()}
            flags = {key: value.get() for key, value in self.port_flags.items()}
            args = build_port_arguments(fields, flags)
            output = Path(fields["output"].strip())
            if output.exists() and not messagebox.askyesno(
                    "Replace output?", f"Replace the existing file?\n\n{output}"):
                return
            stdout, stderr = io.StringIO(), io.StringIO()
            self.root.configure(cursor="watch")
            self.root.update_idletasks()
            try:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = bzcc_port_main(args)
            finally:
                self.root.configure(cursor="")
            result = "\n".join(part.strip() for part in (stdout.getvalue(), stderr.getvalue()) if part.strip())
            self.port_result.set(result or ("Conversion complete." if code == 0 else "Conversion failed."))
            if code:
                messagebox.showerror("BZN conversion failed", self.port_result.get())
            else:
                messagebox.showinfo("BZN conversion complete", self.port_result.get())
        except (OSError, ValueError) as exc:
            self.port_result.set(str(exc))
            messagebox.showerror("BZN conversion failed", str(exc))

    def scan_port_output(self):
        path = self.port_fields["output"].get().strip()
        if not path or not Path(path).is_file():
            messagebox.showerror("Scan output", "Select an existing output BZN first.")
            return
        self._reset_source("bzn", path)
        self.analyze_bzn()
        self.notebook.select(self.dependencies_tab)

    def _build_dependency_tab(self):
        columns = ("status", "type", "filename")
        self.dep_tree = ttk.Treeview(self.dependencies_tab, columns=columns, show="headings")
        self.dep_tree.heading("status", text="Status", command=lambda: self.sort_dependency_column("status", False))
        self.dep_tree.heading("type", text="Type", command=lambda: self.sort_dependency_column("type", False))
        self.dep_tree.heading("filename", text="Filename", command=lambda: self.sort_dependency_column("filename", False))
        self.dep_tree.column("status", width=110, stretch=False)
        self.dep_tree.column("type", width=110, stretch=False)
        self.dep_tree.column("filename", width=900)
        self.dep_tree.tag_configure("missing", foreground="red")
        self.dep_tree.tag_configure("stock", foreground="gray")
        self.dep_tree.pack(fill=tk.BOTH, expand=True)

    def _build_validation_tab(self):
        columns = ("severity", "filename", "line", "location", "message", "suggestion")
        self.issue_tree = ttk.Treeview(self.validation_tab, columns=columns, show="headings")
        self.issue_tree.heading("severity", text="Severity", command=lambda: self.sort_issue_column("severity", False))
        self.issue_tree.heading("filename", text="File", command=lambda: self.sort_issue_column("filename", False))
        self.issue_tree.heading("line", text="Line")
        self.issue_tree.heading("location", text="Section / Key")
        self.issue_tree.heading("message", text="Finding")
        self.issue_tree.heading("suggestion", text="Suggested Fix")
        self.issue_tree.column("severity", width=90, stretch=False)
        self.issue_tree.column("filename", width=145, stretch=False)
        self.issue_tree.column("line", width=55, stretch=False, anchor=tk.CENTER)
        self.issue_tree.column("location", width=180, stretch=False)
        self.issue_tree.column("message", width=455)
        self.issue_tree.column("suggestion", width=300)
        self.issue_tree.tag_configure("critical", foreground="#b00020")
        self.issue_tree.tag_configure("error", foreground="red")
        self.issue_tree.tag_configure("warning", foreground="#9a6700")
        self.issue_tree.pack(fill=tk.BOTH, expand=True)
        self.issue_tree.bind("<Double-1>", self.show_issue_details)

        hint = tk.Label(
            self.validation_tab,
            text=(
                "Double-click a finding for rule/evidence details. Validation is read-only; "
                "files are never modified. Folder and ZIP scans do not require a BZN."
            ),
            fg="gray",
            anchor="w",
        )
        hint.pack(fill=tk.X, pady=(4, 0))

    def _reset_source(self, kind, path):
        self.source_kind = kind
        self.source_path = path
        self.current_file = path if kind == "bzn" else None
        self.dependency_data = []
        self.issue_data = []
        self.referenced_only.set(False)
        self.referenced_check.configure(state=tk.NORMAL if kind == "bzn" else tk.DISABLED)
        self.refresh_dependencies()
        self.refresh_issues()

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[("BZN Files", "*.bzn"), ("All Files", "*.*")])
        if not path:
            return
        self._reset_source("bzn", path)
        self.analyze_bzn()

    def load_folder(self):
        path = filedialog.askdirectory(title="Select folder containing ODF files")
        if not path:
            return
        self._reset_source("folder", path)
        self.issue_data = validate_directory(path, known_odfs=STOCK_SET)
        self.refresh_issues()
        self._update_status()
        self.notebook.select(self.validation_tab)

    def load_zip(self):
        path = filedialog.askopenfilename(filetypes=[("ZIP archives", "*.zip"), ("All Files", "*.*")])
        if not path:
            return
        self._reset_source("zip", path)
        self.issue_data = validate_zip(path, known_odfs=STOCK_SET)
        self.refresh_issues()
        self._update_status()
        self.notebook.select(self.validation_tab)

    def analyze_bzn(self):
        if not self.current_file:
            return

        directory = os.path.dirname(self.current_file)
        try:
            matches = BZNParser(self.current_file).parse()
            self.dependency_data = []
            for odf_base in matches:
                filename = f"{odf_base}.odf"
                is_stock = filename.lower() in STOCK_SET
                exists = self._case_insensitive_exists(directory, filename)
                status = "OK" if exists or is_stock else "MISSING"
                odf_type = "Stock" if is_stock else "Custom"
                self.dependency_data.append((status, odf_type, filename))

            self.dependency_data.sort(key=lambda row: (row[1], row[2].lower()))
            self.refresh_dependencies()
            self._run_odf_validation(directory)
            self._update_status()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def revalidate(self):
        if not self.source_kind or not self.source_path:
            return
        try:
            if self.source_kind == "zip":
                self.issue_data = validate_zip(self.source_path, known_odfs=STOCK_SET)
            elif self.source_kind == "folder":
                self.issue_data = validate_directory(self.source_path, known_odfs=STOCK_SET)
            elif self.source_kind == "bzn":
                self._run_odf_validation(os.path.dirname(self.source_path))
            self.refresh_issues()
            self._update_status()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _run_odf_validation(self, directory):
        filenames = None
        if self.referenced_only.get():
            filenames = [row[2] for row in self.dependency_data if row[1] == "Custom"]
        self.issue_data = validate_directory(directory, filenames=filenames, known_odfs=STOCK_SET)
        self.refresh_issues()

    @staticmethod
    def _case_insensitive_exists(directory, filename):
        target = filename.lower()
        try:
            return any(entry.name.lower() == target for entry in os.scandir(directory) if entry.is_file())
        except OSError:
            return False

    def _update_status(self):
        critical = sum(1 for issue in self.issue_data if issue.severity == "CRITICAL")
        errors = sum(1 for issue in self.issue_data if issue.severity == "ERROR")
        warnings = sum(1 for issue in self.issue_data if issue.severity == "WARNING")

        if self.source_kind == "bzn":
            filename = os.path.basename(self.source_path)
            custom_missing = sum(1 for row in self.dependency_data if row[0] == "MISSING" and row[1] == "Custom")
            prefix = (
                f"{filename}  |  {len(self.dependency_data)} BZN ODF references  |  "
                f"{custom_missing} missing custom"
            )
        elif self.source_kind == "folder":
            root = Path(self.source_path)
            try:
                odf_count = sum(1 for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".odf")
            except OSError:
                odf_count = 0
            prefix = f"Folder: {root.name or root}  |  {odf_count} ODF files"
        elif self.source_kind == "zip":
            prefix = f"ZIP: {os.path.basename(self.source_path)}"
        else:
            prefix = "No source loaded"

        self.status_lbl.config(
            text=f"{prefix}  |  ODF: {critical} critical, {errors} errors, {warnings} warnings",
            fg="#b00020" if critical else ("red" if errors else "black"),
        )

    def refresh_dependencies(self):
        for item in self.dep_tree.get_children():
            self.dep_tree.delete(item)

        data = self.dependency_data
        if self.custom_only.get():
            data = [row for row in data if row[1] == "Custom"]

        for row in data:
            tags = ()
            if row[0] == "MISSING":
                tags = ("missing",)
            elif row[1] == "Stock":
                tags = ("stock",)
            self.dep_tree.insert("", tk.END, values=row, tags=tags)

    def refresh_issues(self):
        for item in self.issue_tree.get_children():
            self.issue_tree.delete(item)
        self.issue_lookup = {}

        for issue in self.issue_data:
            location = issue.section
            if issue.key:
                location = f"{location} / {issue.key}" if location else issue.key
            tag = issue.severity.lower()
            iid = self.issue_tree.insert(
                "",
                tk.END,
                values=(
                    issue.severity,
                    issue.filename,
                    issue.line or "",
                    location,
                    issue.message,
                    issue.suggestion,
                ),
                tags=(tag,),
            )
            self.issue_lookup[iid] = issue

    def show_issue_details(self, _event=None):
        selection = self.issue_tree.selection()
        if not selection:
            return
        issue = self.issue_lookup.get(selection[0])
        if issue is None:
            return

        location = issue.section
        if issue.key:
            location = f"{location} / {issue.key}" if location else issue.key
        if issue.line:
            location += f" (line {issue.line})"

        detail = f"{issue.severity}: {issue.filename}\n{location}\n\n{issue.message}"
        if issue.suggestion:
            detail += f"\n\nSuggested fix:\n{issue.suggestion}"
        if issue.rule_id:
            detail += f"\n\nRule:\n{issue.rule_id}"

        evidence = resolve_evidence(issue.evidence_ids)
        if evidence:
            detail += "\n\nStructured evidence:"
            for item in evidence:
                detail += f"\n\n{item.evidence_id}\n{item.summary()}"
        elif issue.source:
            detail += f"\n\nEvidence / rule source:\n{issue.source}"

        messagebox.showinfo("ODF Validation Finding", detail)

    def sort_dependency_column(self, column, reverse):
        index = {"status": 0, "type": 1, "filename": 2}[column]
        self.dependency_data.sort(key=lambda row: row[index].lower(), reverse=reverse)
        self.refresh_dependencies()
        self.dep_tree.heading(column, command=lambda: self.sort_dependency_column(column, not reverse))

    def sort_issue_column(self, column, reverse):
        if column == "severity":
            self.issue_data.sort(key=lambda x: SEVERITY_ORDER.get(x.severity, 99), reverse=reverse)
        elif column == "filename":
            self.issue_data.sort(key=lambda x: x.filename.lower(), reverse=reverse)
        self.refresh_issues()
        self.issue_tree.heading(column, command=lambda: self.sort_issue_column(column, not reverse))


if __name__ == "__main__":
    root = tk.Tk()
    BZNToolboxApp(root)
    root.mainloop()
