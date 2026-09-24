import json
import os
import shutil
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox

import customtkinter as ctk

from bztoolbox import external, paths
from bztoolbox.app.host import ctk_embedded_root

IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = str(paths.user_data_dir())
CONFIG_FILE = os.path.join(APP_DIR, "ogre_tools_config.json")

APP_USER_MODEL_ID = "GrizzlyOne95.Battlezone98Redux.OgreMeshTools"


def get_resource_path(relative_path):
    """Resources live beside this module, from source and in the toolbox bundle."""
    return os.path.join(MODULE_DIR, relative_path)


def xml_converter_path():
    return external.executable(
        "ogrexmlconverter", fallback=get_resource_path(os.path.join("bin", "OgreXMLConverter.exe")))


def _set_app_user_model_id():
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def apply_window_icon(window):
    """Apply the canonical app icon to a Tk/Toplevel window.

    Uses the bundled branding/app_icon.ico for the titlebar/taskbar
    (iconbitmap) and branding/app_icon.png for iconphoto so taskbar,
    Alt-Tab, and window decorations stay consistent.
    """
    try:
        ico_path = get_resource_path(os.path.join("branding", "app_icon.ico"))
        if os.path.exists(ico_path):
            try:
                window.iconbitmap(ico_path)
            except Exception:
                pass
        png_path = get_resource_path(os.path.join("branding", "app_icon.png"))
        if os.path.exists(png_path):
            try:
                import tkinter as tk

                image = tk.PhotoImage(file=png_path)
                window.iconphoto(True, image)
                window._battlezone_app_icon = image
            except Exception:
                pass
    except Exception:
        pass


_set_app_user_model_id()

WORKER_THREAD_NAME = "ogre-mesh-tools-job"


class ConsoleRedirector:
    """Route print() output into the tool log.

    Standalone, everything is captured (the original behaviour). Inside the
    toolbox only this tool's worker threads are captured; other output goes
    to ``fallback`` so modules do not steal each other's console.
    """

    def __init__(self, log_func, fallback=None, worker_only=False):
        self.log_func = log_func
        self.fallback = fallback
        self.worker_only = worker_only

    def write(self, string):
        if self.worker_only and threading.current_thread().name != WORKER_THREAD_NAME:
            if self.fallback is not None:
                self.fallback.write(string)
            return
        if string.strip():
            self.log_func(string.strip())

    def flush(self):
        if self.fallback is not None and hasattr(self.fallback, "flush"):
            self.fallback.flush()


def obj_output_name(source_name):
    lower_name = source_name.lower()
    if lower_name.endswith(".mesh.xml"):
        return source_name[:-9] + ".obj"
    if lower_name.endswith(".mesh"):
        return source_name[:-5] + ".obj"
    if lower_name.endswith(".xml"):
        return source_name[:-4] + ".obj"
    return source_name + ".obj"


def resolve_executable_path(command):
    if not command:
        return None
    if os.path.isabs(command) or os.path.dirname(command):
        return command if os.path.exists(command) else None
    return shutil.which(command)

class OgreMeshToolsGUI(ctk_embedded_root()):
    def __init__(self, master=None):
        super().__init__(master)

        self._ui_queue = Queue()
        self._main_thread_id = threading.get_ident()

        self.title("OGRE MESH TOOLS")
        self.geometry("1200x850")
        
        # --- ICON (canonical branding/app_icon) ---
        apply_window_icon(self)
        
        # --- THEME & COLORS ---
        self.colors = {
            "bg": "#0a0a0a",
            "fg": "#d4d4d4",
            "highlight": "#00ff00", # Neon Green
            "warning": "#ffff44",   # Amber/Gold
            "accent": "#00ffff",    # Cyan
            "dark": "#1a1a1a"
        }
        
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green") # matches highlight
        
        self.configure(fg_color=self.colors["bg"])
        
        self.resource_dir = get_resource_path(".")
        self.load_custom_fonts()
        
        # --- VARIABLES ---
        self.input_path = ctk.StringVar()
        self.output_path = ctk.StringVar()
        self.do_gltf = ctk.BooleanVar(value=True)
        self.do_obj = ctk.BooleanVar(value=False)
        self.do_normals = ctk.BooleanVar(value=False)
        self.batch_mode = ctk.BooleanVar(value=False)
        self.blender_path = ctk.StringVar()
        self.last_output_dir = ""
        
        self.load_config()
        self.setup_ui()
        
        # Capture stdout/stderr AFTER UI is setup
        embedded = self._toolbox_standalone is None
        sys.stdout = ConsoleRedirector(self.log, fallback=sys.stdout, worker_only=embedded)
        sys.stderr = ConsoleRedirector(self.log, fallback=sys.stderr, worker_only=embedded)
        self.after(50, self._process_ui_queue)
        
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    self.blender_path.set(cfg.get("blender_path", "") or external.executable("blender", "blender"))
            except: pass
        else:
            self.blender_path.set(external.executable("blender", "blender"))

    def save_config(self):
        cfg = {
            "blender_path": self.blender_path.get()
        }
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=4)
        except: pass
        
    def load_custom_fonts(self):
        self.main_font = "Consolas"
        if IS_WINDOWS:
            font_path = get_resource_path("BZONE.ttf")
            if os.path.exists(font_path):
                # AddFontResourceExW flag 0x10 is FR_PRIVATE (not enumerable by others)
                import ctypes
                ctypes.windll.gdi32.AddFontResourceExW(font_path, 0x10, 0)
                self.main_font = "BZONE"
                print(f"Loaded custom font: {self.main_font}")

    def setup_ui(self):
        # Header
        self.header = ctk.CTkLabel(self, text="OGRE MESH TOOLS", 
                                  font=(self.main_font, 32, "bold"), 
                                  text_color=self.colors["highlight"])
        self.header.pack(pady=(20, 10))
        
        self.subtitle = ctk.CTkLabel(self, text="BATTLEZONE CONVERSION UTILITY", 
                                    font=(self.main_font, 14), 
                                    text_color=self.colors["accent"])
        self.subtitle.pack(pady=(0, 20))

        # --- ACTION BUTTONS (Packed bottom-up to ensure visibility) ---
        self.open_folder_btn = ctk.CTkButton(self, text="OPEN EXPORT DIRECTORY", 
                                            command=self.open_output_folder,
                                            font=(self.main_font, 12),
                                            fg_color="transparent",
                                            text_color=self.colors["accent"],
                                            hover_color=self.colors["dark"])
        self.open_folder_btn.pack(side="bottom", pady=(0, 20))

        self.run_btn = ctk.CTkButton(self, text="PROCESS MESHES", 
                                    command=self.start_process, 
                                    font=(self.main_font, 16, "bold"), 
                                    height=50, 
                                    fg_color=self.colors["dark"], 
                                    border_width=2, 
                                    border_color=self.colors["highlight"],
                                    hover_color=self.colors["highlight"],
                                    text_color=self.colors["highlight"])
        self.run_btn.configure(hover_color="#006600")
        self.run_btn.pack(side="bottom", fill="x", padx=45, pady=(10, 5))

        # Main Frame setup for splits
        self.main_container = ctk.CTkFrame(self, fg_color=self.colors["bg"])
        self.main_container.pack(fill="both", expand=True, padx=40, pady=10)

        # Left Column (Settings and operations)
        self.left_col = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # Right Column (Preview)
        self.right_col = ctk.CTkFrame(self.main_container, fg_color=self.colors["dark"])
        self.right_col.pack(side="right", fill="both", expand=True)

        ctk.CTkLabel(self.right_col, text="MESH PREVIEW", font=(self.main_font, 12, "bold"), text_color=self.colors["highlight"]).pack(anchor="w", padx=10, pady=(5,0))
        
        try:
            from bztoolbox.modules.meshes import ogre_preview
            self.preview_frame = ogre_preview.OgrePreviewFrame(self.right_col)
            self.preview_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))
        except (ImportError, Exception):
            lbl = ctk.CTkLabel(self.right_col, text="Ogre preview not available.\nRun 'py -3.10 -m pip install ogre-python' first.")
            lbl.pack(expand=True)
            self.preview_frame = None

        # --- INPUT SECTION ---
        self.input_frame = ctk.CTkFrame(self.left_col, fg_color=self.colors["dark"])
        self.input_frame.pack(fill="x", pady=10, padx=5)
        
        ctk.CTkLabel(self.input_frame, text="INPUT SOURCE", font=(self.main_font, 12, "bold"), text_color=self.colors["highlight"]).pack(anchor="w", padx=10, pady=(5,0))
        
        self.path_row = ctk.CTkFrame(self.input_frame, fg_color="transparent")
        self.path_row.pack(fill="x", padx=10, pady=(10, 5))
        
        self.input_entry = ctk.CTkEntry(self.path_row, textvariable=self.input_path, placeholder_text="Select a .mesh file or directory...", fg_color="#050505", border_color=self.colors["highlight"])
        self.input_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.preview_btn = ctk.CTkButton(self.path_row, text="PREVIEW", command=self.preview_mesh, font=(self.main_font, 12, "bold"), fg_color=self.colors["dark"], border_width=1, border_color=self.colors["accent"], hover_color="#222", text_color=self.colors["accent"])
        self.preview_btn.pack(side="right", padx=(10, 0))

        self.browse_btn = ctk.CTkButton(self.path_row, text="BROWSE", command=self.browse_input, font=(self.main_font, 12), fg_color=self.colors["dark"], border_width=1, border_color=self.colors["highlight"], hover_color="#222")
        self.browse_btn.pack(side="right")
        
        self.out_row = ctk.CTkFrame(self.input_frame, fg_color="transparent")
        self.out_row.pack(fill="x", padx=10, pady=(5, 10))
        
        ctk.CTkLabel(self.out_row, text="OUTPUT:", font=(self.main_font, 11), text_color=self.colors["fg"]).pack(side="left", padx=(0, 8))
        
        self.output_entry = ctk.CTkEntry(self.out_row, textvariable=self.output_path, placeholder_text="Output Destination (Optional)...", fg_color="#050505", border_color=self.colors["highlight"])
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.browse_out_btn = ctk.CTkButton(self.out_row, text="BROWSE", command=self.browse_output, font=(self.main_font, 12), fg_color=self.colors["dark"], border_width=1, border_color=self.colors["highlight"], hover_color="#222")
        self.browse_out_btn.pack(side="right")
        
        self.mode_switch = ctk.CTkSwitch(self.input_frame, text="BATCH DIRECTORY MODE", variable=self.batch_mode, font=(self.main_font, 11), progress_color=self.colors["highlight"])
        self.mode_switch.pack(anchor="w", padx=10, pady=(0, 10))

        # --- CONFIG SECTION ---
        self.cfg_frame = ctk.CTkFrame(self.left_col, fg_color=self.colors["dark"])
        self.cfg_frame.pack(fill="x", pady=10, padx=5)
        
        ctk.CTkLabel(self.cfg_frame, text="SETTINGS", font=(self.main_font, 12, "bold"), text_color=self.colors["highlight"]).pack(anchor="w", padx=10, pady=(5,0))
        
        self.blender_row = ctk.CTkFrame(self.cfg_frame, fg_color="transparent")
        self.blender_row.pack(fill="x", padx=10, pady=(5, 5))
        
        ctk.CTkLabel(self.blender_row, text="Blender Path:", font=(self.main_font, 11)).pack(side="left", padx=(0, 10))
        self.blender_entry = ctk.CTkEntry(self.blender_row, textvariable=self.blender_path, fg_color="#050505", border_color=self.colors["highlight"], height=24)
        self.blender_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.blender_browse = ctk.CTkButton(self.blender_row, text="...", width=30, height=24, command=self.browse_blender)
        self.blender_browse.pack(side="right")

        # --- PROGRESS SECTION ---
        self.progress_frame = ctk.CTkFrame(self.left_col, fg_color="transparent")
        self.progress_frame.pack(fill="x", pady=(10, 0), padx=5)
        
        self.progress_label = ctk.CTkLabel(self.progress_frame, text="READY", font=(self.main_font, 10), text_color=self.colors["fg"])
        self.progress_label.pack(side="left")
        
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, progress_color=self.colors["highlight"], fg_color=self.colors["dark"])
        self.progress_bar.pack(side="right", fill="x", expand=True, padx=(10, 0))
        self.progress_bar.set(0)

        # --- OPERATIONS ---
        self.ops_frame = ctk.CTkFrame(self.left_col, fg_color=self.colors["dark"])
        self.ops_frame.pack(fill="x", pady=10, padx=5)
        
        ctk.CTkLabel(self.ops_frame, text="OPERATIONS", font=(self.main_font, 12, "bold"), text_color=self.colors["highlight"]).pack(anchor="w", padx=10, pady=(5,5))
        
        # glTF Row
        self.gltf_row = ctk.CTkFrame(self.ops_frame, fg_color="transparent")
        self.gltf_row.pack(fill="x", padx=20, pady=2)
        self.check_gltf = ctk.CTkCheckBox(self.gltf_row, text="CONVERT TO glTF (.glb)", variable=self.do_gltf, font=(self.main_font, 12), border_color=self.colors["highlight"], checkmark_color=self.colors["bg"])
        self.check_gltf.pack(side="left")
        ctk.CTkLabel(self.gltf_row, text="[ANIMATED / RIGGED - REQUIRES BLENDER]", font=(self.main_font, 10), text_color=self.colors["accent"]).pack(side="left", padx=10)
        
        # OBJ Row
        self.obj_row = ctk.CTkFrame(self.ops_frame, fg_color="transparent")
        self.obj_row.pack(fill="x", padx=20, pady=5)
        self.check_obj = ctk.CTkCheckBox(self.obj_row, text="CONVERT TO OBJ", variable=self.do_obj, font=(self.main_font, 12), border_color=self.colors["highlight"], checkmark_color=self.colors["bg"])
        self.check_obj.pack(side="left")
        ctk.CTkLabel(self.obj_row, text="[STATIC MESH - STANDALONE]", font=(self.main_font, 10), text_color=self.colors["fg"]).pack(side="left", padx=10)
        
        # Normals
        self.check_normals = ctk.CTkCheckBox(self.ops_frame, text="RECALCULATE NORMALS (Requires XML)", variable=self.do_normals, font=(self.main_font, 12), border_color=self.colors["highlight"], checkmark_color=self.colors["bg"])
        self.check_normals.pack(anchor="w", padx=20, pady=5)

        # --- LOGGING ---
        self.log_label = ctk.CTkLabel(self.left_col, text="TERMINAL OUTPUT", font=(self.main_font, 12, "bold"), text_color=self.colors["highlight"])
        self.log_label.pack(anchor="w", padx=5, pady=(10, 0))
        
        self.log_box = ctk.CTkTextbox(self.left_col, fg_color="#050505", text_color=self.colors["fg"], font=("Consolas", 12), border_width=1, border_color=self.colors["highlight"])
        self.log_box.pack(fill="both", expand=True, padx=5, pady=(5, 10))

    def _queue_ui_call(self, callback, *args, **kwargs):
        self._ui_queue.put((callback, args, kwargs))

    def _process_ui_queue(self):
        try:
            while True:
                callback, args, kwargs = self._ui_queue.get_nowait()
                callback(*args, **kwargs)
        except Empty:
            pass

        try:
            self.after(50, self._process_ui_queue)
        except Exception:
            pass

    def _append_log_ui(self, message, color=None):
        if not message:
            return
        for line in str(message).splitlines():
            self.log_box.insert("end", f"> {line}\n")
        self.log_box.see("end")

    def _clear_log_ui(self):
        self.log_box.delete("1.0", "end")

    def _set_progress_label_ui(self, text):
        self.progress_label.configure(text=text)

    def _set_progress_ui(self, value):
        self.progress_bar.set(value)

    def _set_run_state_ui(self, enabled, text):
        self.run_btn.configure(state="normal" if enabled else "disabled", text=text)

    def _show_message_ui(self, kind, title, message):
        if kind == "error":
            messagebox.showerror(title, message)
        else:
            messagebox.showinfo(title, message)

    def log(self, message, color=None):
        text = str(message).strip()
        if not text:
            return
        if threading.get_ident() == self._main_thread_id:
            self._append_log_ui(text, color=color)
        else:
            self._queue_ui_call(self._append_log_ui, text, color)

    def _clear_log(self):
        if threading.get_ident() == self._main_thread_id:
            self._clear_log_ui()
        else:
            self._queue_ui_call(self._clear_log_ui)

    def _set_progress_label(self, text):
        if threading.get_ident() == self._main_thread_id:
            self._set_progress_label_ui(text)
        else:
            self._queue_ui_call(self._set_progress_label_ui, text)

    def _set_progress(self, value):
        if threading.get_ident() == self._main_thread_id:
            self._set_progress_ui(value)
        else:
            self._queue_ui_call(self._set_progress_ui, value)

    def _set_run_state(self, enabled, text):
        if threading.get_ident() == self._main_thread_id:
            self._set_run_state_ui(enabled, text)
        else:
            self._queue_ui_call(self._set_run_state_ui, enabled, text)

    def _show_message(self, kind, title, message):
        if threading.get_ident() == self._main_thread_id:
            self._show_message_ui(kind, title, message)
        else:
            self._queue_ui_call(self._show_message_ui, kind, title, message)

    def _resolve_output_dir(self, requested_output, default_dir):
        output_dir = requested_output.strip() if requested_output else default_dir
        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

    def _validate_job_tools(self, job, xml_converter):
        if not os.path.exists(xml_converter):
            raise FileNotFoundError(f"Missing OgreXMLConverter.exe at {xml_converter}")

        if job["do_gltf"]:
            resolved_blender = resolve_executable_path(job["blender_path"])
            if not resolved_blender:
                raise FileNotFoundError(
                    f"Blender executable not found: {job['blender_path']}"
                )
            return resolved_blender

        return None

    def _run_command(self, cmd, check=True):
        self.log(f"Running: {' '.join(str(part) for part in cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
        )

        if result.stdout.strip():
            self.log(result.stdout.strip())
        if result.stderr.strip():
            self.log(result.stderr.strip(), self.colors["warning"])

        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                cmd,
                output=result.stdout,
                stderr=result.stderr,
            )
        return result

    @staticmethod
    def _summarize_errors(errors):
        if not errors:
            return ""
        preview = errors[:8]
        summary = "\n".join(f"- {err}" for err in preview)
        if len(errors) > len(preview):
            summary += f"\n- ... and {len(errors) - len(preview)} more"
        return summary

    def browse_blender(self):
        f = filedialog.askopenfilename(filetypes=[("Executable", "*.exe"), ("All Files", "*.*")])
        if f: 
            self.blender_path.set(f)
            self.save_config()

    def browse_input(self):
        if self.batch_mode.get():
            d = filedialog.askdirectory()
            if d: self.input_path.set(d)
        else:
            f = filedialog.askopenfilename(filetypes=[("Ogre Mesh", "*.mesh"), ("Ogre XML", "*.xml"), ("All Files", "*.*")])
            if f: self.input_path.set(f)

    def browse_output(self):
        d = filedialog.askdirectory()
        if d: self.output_path.set(d)

    def open_output_folder(self):
        if self.last_output_dir and os.path.exists(self.last_output_dir):
            if IS_WINDOWS:
                os.startfile(self.last_output_dir)
            else:
                subprocess.run(["xdg-open", self.last_output_dir], creationflags=CREATE_NO_WINDOW)
        else:
            messagebox.showinfo("Note", "No export directory has been created yet.")

    def preview_mesh(self):
        path = self.input_path.get()
        
        if not path or not os.path.exists(path):
            messagebox.showerror("Error", "Please select a valid input mesh or directory to preview.")
            return
            
        if self.batch_mode.get():
            # In batch mode, try to find the first .mesh file to preview
            for root, _, files in os.walk(path):
                for f in files:
                    if f.lower().endswith('.mesh'):
                        path = os.path.join(root, f)
                        break
                if path.lower().endswith('.mesh'):
                    break
                    
            if not path.lower().endswith('.mesh'):
                messagebox.showerror("Error", "No .mesh files found in the selected batch directory to preview.")
                return
                
        if not path.lower().endswith('.mesh'):
            messagebox.showerror("Error", "Selected file is not a valid .mesh file.")
            return
            
        self.log(f"Loading native preview for: {os.path.basename(path)}")
        try:
            if self.preview_frame:
                self.preview_frame.load_mesh(path)
            else:
                self.log("Preview frame failed to initialize earlier.", self.colors["warning"])
        except Exception as e:
            self.log(f"Failed to load mesh in viewer: {str(e)}", self.colors["warning"])

    def start_process(self):
        input_path = self.input_path.get().strip()
        if not input_path or not os.path.exists(input_path):
            messagebox.showerror("Error", "Input path does not exist.")
            return

        if not (self.do_normals.get() or self.do_obj.get() or self.do_gltf.get()):
            messagebox.showerror("Error", "Select at least one operation.")
            return

        self.save_config()

        job = {
            "input_path": os.path.abspath(input_path),
            "output_path": self.output_path.get().strip(),
            "do_normals": self.do_normals.get(),
            "do_obj": self.do_obj.get(),
            "do_gltf": self.do_gltf.get(),
            "batch_mode": self.batch_mode.get(),
            "blender_path": self.blender_path.get().strip() or "blender",
        }

        self._set_run_state(False, "PROCESSING...")
        self._clear_log()
        self._set_progress(0)
        self.log("Starting operation sequence...")

        thread = threading.Thread(target=self.run_operations, args=(job,), daemon=True, name=WORKER_THREAD_NAME)
        thread.start()

    def run_operations(self, job):
        errors = []

        try:
            input_p = job["input_path"]
            requested_output = job["output_path"]
            xml_converter = xml_converter_path()
            is_batch = job["batch_mode"]
            blender_exe = self._validate_job_tools(job, xml_converter)

            files_to_process = []
            if is_batch:
                for root, _, files in os.walk(input_p):
                    for f in files:
                        if f.lower().endswith((".mesh", ".xml")):
                            files_to_process.append(os.path.join(root, f))
            else:
                files_to_process = [input_p]

            if job["do_normals"]:
                self.log(f"--- STARTING NORMAL RECALCULATION ({len(files_to_process)} files) ---")
                self._set_progress_label("RECALCULATING NORMALS...")
                from bztoolbox.modules.meshes import recalculate_normals

                corrected_count = 0
                total_files = max(len(files_to_process), 1)
                for i, f_path in enumerate(files_to_process):
                    progress = (i / total_files) * 0.33 if (job["do_obj"] or job["do_gltf"]) else (i / total_files)
                    self._set_progress(progress)

                    f_name = os.path.basename(f_path)
                    target_xml = f_path
                    temp_xml = None

                    try:
                        if f_path.lower().endswith(".mesh"):
                            self._run_command([xml_converter, f_path])
                            candidate_paths = [f_path + ".xml", os.path.splitext(f_path)[0] + ".xml"]
                            temp_xml = next((path for path in candidate_paths if os.path.exists(path)), None)
                            target_xml = temp_xml or candidate_paths[0]

                        if not os.path.exists(target_xml):
                            raise FileNotFoundError(f"Could not find XML for {f_name}")

                        status = recalculate_normals.recalculate_normals(target_xml)
                        if status == "CHANGED":
                            self.log(f"UPDATED: Corrected normals for {f_name}")
                            corrected_count += 1
                        elif status == "UNCHANGED":
                            self.log(f"CHECKED: Normals already correct for {f_name}")
                        else:
                            raise RuntimeError(f"Normal recalculation failed for {f_name}")

                        if temp_xml and status == "CHANGED":
                            self.log(f"Exporting updated {f_name} back to binary mesh...")
                            self._run_command([xml_converter, target_xml])
                    except Exception as exc:
                        errors.append(f"Normals: {f_name}: {exc}")
                        self.log(f"WARNING: {f_name}: {exc}", self.colors["warning"])
                    finally:
                        if temp_xml and os.path.exists(temp_xml):
                            try:
                                os.remove(temp_xml)
                            except OSError:
                                pass

                self.log(f"--- NORMAL RECALCULATION COMPLETE: {corrected_count}/{len(files_to_process)} corrected ---")

            if job["do_obj"]:
                self._set_progress_label("CONVERTING TO OBJ...")
                self._set_progress(0.5 if job["do_gltf"] else 0.8)
                self.log("--- STARTING OBJ CONVERSION ---")

                try:
                    from bztoolbox.modules.meshes import MeshToObj

                    default_output = os.path.join(
                        input_p if is_batch else os.path.dirname(input_p),
                        "OBJ_Export",
                    )
                    output_dir = self._resolve_output_dir(requested_output, default_output)
                    self.last_output_dir = output_dir

                    xml_conv = MeshToObj.OgreXMLConverter(os.path.dirname(xml_converter))

                    if is_batch:
                        output_p = Path(output_dir)
                        xml_dir = output_p / "xml_temp"
                        xml_dir.mkdir(parents=True, exist_ok=True)

                        try:
                            self.log("Converting meshes to XML...")
                            xml_files = xml_conv.batch_convert(
                                input_p,
                                xml_dir,
                                extensions=[".mesh"],
                            )
                            if not xml_files:
                                raise RuntimeError("No .mesh files were converted to XML.")

                            self.log("Converting XML to OBJ...")
                            for xml_f in xml_files:
                                xml_path = Path(xml_f)
                                rel_xml = xml_path.relative_to(xml_dir)
                                obj_rel = rel_xml.with_name(obj_output_name(rel_xml.name))
                                obj_file = output_p / obj_rel
                                obj_file.parent.mkdir(parents=True, exist_ok=True)

                                converter = MeshToObj.OgreXMLToOBJ()
                                converter.convert(
                                    xml_f,
                                    obj_file,
                                    create_mtl=True,
                                    texture_search_roots=[input_p],
                                )
                        finally:
                            if xml_dir.exists():
                                shutil.rmtree(xml_dir, ignore_errors=True)
                    else:
                        output_p = Path(output_dir)
                        output_p.mkdir(parents=True, exist_ok=True)
                        target_obj = output_p / obj_output_name(Path(input_p).name)

                        cleanup_xml = False
                        if input_p.lower().endswith(".xml"):
                            xml_f = input_p
                        else:
                            xml_f = xml_conv.convert_to_xml(input_p)
                            cleanup_xml = True

                        if not xml_f:
                            raise RuntimeError("XML conversion failed.")

                        try:
                            converter = MeshToObj.OgreXMLToOBJ()
                            converter.convert(
                                xml_f,
                                target_obj,
                                create_mtl=True,
                                texture_search_roots=[Path(input_p).parent],
                            )
                        finally:
                            if cleanup_xml and os.path.exists(xml_f):
                                os.remove(xml_f)

                    self.log("OBJ Conversion completed.")
                except Exception as exc:
                    errors.append(f"OBJ: {exc}")
                    self.log(f"OBJ ERROR: {exc}", self.colors["warning"])

            if job["do_gltf"]:
                self._set_progress_label("CONVERTING TO glTF (BLENDER)...")
                self._set_progress(0.9)
                self.log("--- STARTING glTF CONVERSION (Blender) ---")

                try:
                    gltf_script = get_resource_path(os.path.join("blender", "batch_ogre_to_gltf.py"))
                    default_output = os.path.join(
                        input_p if is_batch else os.path.dirname(input_p),
                        "glTF_Export",
                    )
                    output_dir = self._resolve_output_dir(requested_output, default_output)
                    self.last_output_dir = output_dir

                    if not is_batch and not input_p.lower().endswith(".mesh"):
                        raise RuntimeError("Single-file glTF conversion requires a .mesh input.")

                    result = self._run_command(
                        [
                            blender_exe,
                            "-b",
                            "-P",
                            gltf_script,
                            "--",
                            input_p,
                            output_dir,
                            xml_converter,
                        ],
                        check=False,
                    )
                    if result.returncode != 0:
                        raise RuntimeError(f"Blender exited with code {result.returncode}.")

                    self.log("glTF Conversion completed.")
                except Exception as exc:
                    errors.append(f"glTF: {exc}")
                    self.log(f"glTF ERROR: {exc}", self.colors["warning"])

            self._set_progress(1.0)

            if errors:
                summary = self._summarize_errors(errors)
                self._set_progress_label("COMPLETE WITH ERRORS")
                self.log("OPERATION SEQUENCE COMPLETED WITH ERRORS.", self.colors["warning"])
                self.log(summary, self.colors["warning"])
                self._show_message("error", "Completed With Errors", summary)
            else:
                self._set_progress_label("COMPLETE")
                self.log("OPERATION SEQUENCE COMPLETE.", self.colors["highlight"])
                self._show_message("info", "Success", "All operations completed successfully.")

        except Exception as exc:
            self._set_progress_label("FAILED")
            self.log(f"CRITICAL ERROR: {exc}", self.colors["warning"])
            self.log(traceback.format_exc(), self.colors["warning"])
            self._show_message("error", "Error", f"An error occurred: {exc}")
        finally:
            self._set_run_state(True, "PROCESS MESHES")

if __name__ == "__main__":
    app = OgreMeshToolsGUI()
    app.mainloop()
