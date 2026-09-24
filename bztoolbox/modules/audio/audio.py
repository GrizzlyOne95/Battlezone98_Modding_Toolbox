import os
import sys
import csv
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import ctypes
from datetime import datetime

from bztoolbox.modules.audio import processing
from bztoolbox.app.host import EmbeddedRoot
from bztoolbox.app.fonts import bz_font

# --- UTILITY FUNCTIONS ---
APP_USER_MODEL_ID = "GrizzlyOne95.Battlezone98Redux.AudioTool"


def _set_app_user_model_id():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def get_resource_path(relative_path):
    """Resources live beside this module, from source and in the toolbox bundle."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, relative_path)


def apply_window_icon(window):
    """Apply the canonical app icon to a Tk/Toplevel window."""
    try:
        ico_path = get_resource_path(os.path.join("branding", "app_icon.ico"))
        if not os.path.exists(ico_path):
            ico_path = get_resource_path("branding/app_icon.ico")
        if os.path.exists(ico_path):
            try:
                window.iconbitmap(ico_path)
            except Exception:
                pass
        png_path = get_resource_path(os.path.join("branding", "app_icon.png"))
        if os.path.exists(png_path):
            try:
                image = tk.PhotoImage(file=png_path)
                window.iconphoto(True, image)
                window._battlezone_app_icon = image
            except Exception:
                pass
    except Exception:
        pass


_set_app_user_model_id()

# Resource Constants
COMM_BEEP = get_resource_path("commbeep.wav")
UNIT_BEEP = get_resource_path("unitbeep.wav")

WAV_PROFILE_RADIO = "radio"
WAV_PROFILE_LOOP = "loop"


class ToolTip:
    def __init__(self, widget, text, bg="#1a1a1a", fg="#00ffff"):
        self.widget = widget
        self.text = text
        self.bg = bg
        self.fg = fg
        self.tip_window = None
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 20
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify='left',
                       background=self.bg, foreground=self.fg, 
                       relief='solid', borderwidth=1, font=("Consolas", "9"))
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

class BZRadio(EmbeddedRoot):
    def __init__(self, master=None):
        super().__init__(master)
        
        # --- WINDOW CONFIGURATION ---
        self.title("BZRadio - Battlezone 98 Redux Audio Tool")
        self.geometry("800x950")
        self.custom_beep_path = None
        
        # Theme Configuration (Matching cmd.py BZ98R)
        self.colors = {
            "bg": "#0a0a0a", "fg": "#d4d4d4",
            "highlight": "#00ff00", "dark_highlight": "#004400", "accent": "#00ffff"
        }
        self.configure(bg=self.colors["bg"])
        
        # Font Loading
        self.font_name = "Consolas"
        self.load_custom_fonts()

        # Set the window icon (canonical branding/app_icon).
        try:
            apply_window_icon(self)
        except Exception:
            pass

        self.setup_styles()
        self.setup_ui()

    def load_custom_fonts(self):
        self.font_name = bz_font(self.font_name)

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('default')
        
        c = self.colors
        main_font = (self.font_name, 10)
        bold_font = (self.font_name, 11, "bold")
        header_font = (self.font_name, 12, "bold")

        style.configure(".", background=c["bg"], foreground=c["fg"], font=main_font, bordercolor=c["dark_highlight"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TLabelframe", background=c["bg"], bordercolor=c["highlight"])
        style.configure("TLabelframe.Label", background=c["bg"], foreground=c["highlight"], font=bold_font)
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        # BZRadio.* names: generic "Header.TLabel" is shared (and restyled) by other tools
        style.configure("BZRadio.Header.TLabel", foreground=c["accent"], font=(self.font_name, 24, "bold"))
        style.configure("BZRadio.Sub.TLabel", foreground=c["fg"], font=(self.font_name, 10))
        
        style.configure("TButton", background="#1a1a1a", foreground=c["fg"], borderwidth=1, focuscolor=c["highlight"])
        style.map("TButton", background=[("active", c["dark_highlight"])], foreground=[("active", c["highlight"])])
        
        style.configure("Action.TButton", font=bold_font, foreground=c["highlight"])
        style.configure("Primary.TButton", font=bold_font, foreground=c["accent"])
        
        style.configure("TRadiobutton", background=c["bg"], foreground=c["fg"], indicatorcolor=c["bg"], indicatorrelief="raised")
        style.map("TRadiobutton", indicatorcolor=[("selected", c["highlight"])], foreground=[("selected", c["highlight"])])
        
        style.configure("TCheckbutton", background=c["bg"], foreground=c["fg"], indicatorcolor=c["bg"], indicatorrelief="raised")
        style.map("TCheckbutton", indicatorcolor=[("selected", c["highlight"])], foreground=[("selected", c["highlight"])])

        style.configure("BZ.Horizontal.TProgressbar", thickness=20, background=c["highlight"], troughcolor="#050505", bordercolor=c["dark_highlight"])
        
        # Combobox style
        style.map("TCombobox", fieldbackground=[("readonly", "#1a1a1a")], selectbackground=[("readonly", c["dark_highlight"])], selectforeground=[("readonly", c["highlight"])])

    def setup_ui(self):
        # --- HEADER SECTION ---
        header_frame = ttk.Frame(self)
        header_frame.pack(pady=(20, 5))
        ttk.Label(header_frame, text="BZRadio", style="BZRadio.Header.TLabel").pack()
        ttk.Label(header_frame, text="AUDIO ARCHITECT FOR BZ98 REDUX", style="BZRadio.Sub.TLabel").pack()

        # --- MAIN CONTAINER ---
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # --- 1. CONFIGURATION ---
        config_group = ttk.LabelFrame(main_frame, text=" SYSTEM CONFIGURATION ", padding=10)
        config_group.pack(fill="x", pady=5)

        # Process Mode (Batch vs Single)
        self.process_mode = tk.StringVar(value="batch")
        mode_frame = ttk.Frame(config_group)
        mode_frame.pack(fill="x", pady=5)
        ttk.Label(mode_frame, text="INPUT SOURCE:", font=(self.font_name, 10, "bold"), foreground=self.colors["accent"]).pack(side="left", padx=(0, 10))
        ttk.Radiobutton(mode_frame, text="BATCH FOLDER", variable=self.process_mode, value="batch").pack(side="left", padx=10)
        ttk.Radiobutton(mode_frame, text="SINGLE FILE", variable=self.process_mode, value="single").pack(side="left", padx=10)

        # Privacy
        self.strip_metadata_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(config_group, text="STRIP METADATA (PII Scrub)", variable=self.strip_metadata_var).pack(anchor="w", pady=5)

        # --- 2. RADIO TRANSMISSION (WAV) ---
        wav_group = ttk.LabelFrame(main_frame, text=" RADIO TRANSMISSION PROTOCOL (WAV) ", padding=10)
        wav_group.pack(fill="x", pady=10)

        profile_row = ttk.Frame(wav_group)
        profile_row.pack(fill="x", pady=5)
        ttk.Label(profile_row, text="WAV PROFILE:").pack(side="left")
        self.wav_profile_var = tk.StringVar(value="Radio VO (22050Hz)")
        self.wav_profile_dropdown = ttk.Combobox(profile_row, textvariable=self.wav_profile_var, state="readonly", width=28)
        self.wav_profile_dropdown["values"] = ["Radio VO (22050Hz)", "Thrust/Turbo Loop (11025Hz)"]
        self.wav_profile_dropdown.pack(side="left", padx=(5, 20))
        self.wav_profile_dropdown.bind("<<ComboboxSelected>>", self.update_wav_profile_ui)

        # Effects Row
        fx_row = ttk.Frame(wav_group)
        fx_row.pack(fill="x", pady=5)
        
        self.phaser_var = tk.BooleanVar(value=False)
        self.phaser_check = ttk.Checkbutton(fx_row, text="ENABLE PHASER", variable=self.phaser_var)
        self.phaser_check.pack(side="left", padx=(0, 15))
        
        self.echo_var = tk.BooleanVar(value=False)
        self.echo_check = ttk.Checkbutton(fx_row, text="ENABLE ECHO", variable=self.echo_var)
        self.echo_check.pack(side="left", padx=(0, 15))

        # Echo Delay Slider
        slider_frame = ttk.Frame(fx_row)
        slider_frame.pack(side="left", fill="x", expand=True)
        
        self.echo_delay_var = tk.DoubleVar(value=40)
        self.echo_label = ttk.Label(slider_frame, text="DELAY: 40ms", width=12)
        self.echo_label.pack(side="left", padx=5)
        
        self.echo_slider = ttk.Scale(slider_frame, from_=10, to=100, variable=self.echo_delay_var, orient="horizontal", command=self.update_slider_label)
        self.echo_slider.pack(side="left", fill="x", expand=True, padx=5)

        # Tone & Intensity
        opts_row = ttk.Frame(wav_group)
        opts_row.pack(fill="x", pady=10)
        
        # Squelch Tone
        ttk.Label(opts_row, text="SQUELCH TONE:").pack(side="left")
        self.beep_var = tk.StringVar(value="commbeep.wav (Radio/Orders)")
        self.beep_dropdown = ttk.Combobox(opts_row, textvariable=self.beep_var, state="readonly", width=35)
        self.beep_dropdown['values'] = ["commbeep.wav (Radio/Orders)", "unitbeep.wav (Unit Responses)", "Custom...", "None"]
        self.beep_dropdown.pack(side="left", padx=(5, 20))
        self.beep_dropdown.bind("<<ComboboxSelected>>", self.check_custom_beep)

        # Intensity
        ttk.Label(opts_row, text="INTENSITY:").pack(side="left")
        self.intensity_var = tk.StringVar(value="medium")
        self.intensity_dropdown = ttk.Combobox(opts_row, textvariable=self.intensity_var, state="readonly", width=10)
        self.intensity_dropdown['values'] = ["none", "light", "medium", "heavy"]
        self.intensity_dropdown.pack(side="left", padx=5)

        # Action Button
        self.btn_radio = ttk.Button(wav_group, text="INITIATE WAV PROCESSING", command=lambda: self.start_thread("wav"), style="Action.TButton")
        self.btn_radio.pack(fill="x", pady=(10, 0), ipady=5)

        # --- 3. MUSIC PROCESSING (OGG) ---
        ogg_group = ttk.LabelFrame(main_frame, text=" MUSIC ENCODING (OGG) ", padding=10)
        ogg_group.pack(fill="x", pady=5)
        
        self.btn_ogg = ttk.Button(ogg_group, text="INITIATE OGG ENCODING", command=lambda: self.start_thread("ogg"), style="Primary.TButton")
        self.btn_ogg.pack(fill="x", ipady=5)

        # --- 4. UTILITIES ---
        util_frame = ttk.Frame(main_frame)
        util_frame.pack(fill="x", pady=10)
        
        self.btn_csv = ttk.Button(util_frame, text="EXPORT TIMING MANIFEST (CSV)", command=self.export_csv)
        self.btn_csv.pack(fill="x")

        # --- 5. LOG & PROGRESS ---
        log_frame = ttk.LabelFrame(main_frame, text=" HUD LOG ", padding=10)
        log_frame.pack(fill="both", expand=True, pady=5)
        
        self.log_box = tk.Text(log_frame, height=10, bg="#050505", fg=self.colors["fg"], 
                             font=("Consolas", 9), state="disabled", relief="flat", padx=5, pady=5)
        self.log_box.pack(fill="both", expand=True)

        # Log Tags
        self.log_box.tag_config("timestamp", foreground="#666666")
        self.log_box.tag_config("success", foreground=self.colors["highlight"])
        self.log_box.tag_config("warning", foreground="#ffff00")
        self.log_box.tag_config("error", foreground="#ff0000")
        
        self.progress = ttk.Progressbar(main_frame, style="BZ.Horizontal.TProgressbar", mode="determinate")
        self.progress.pack(fill="x", pady=(5, 0))
        
        self.status_label = tk.Label(main_frame, text="SYSTEM READY", bg=self.colors["bg"], fg="#666666", font=("Consolas", 8))
        self.status_label.pack(pady=2)

        self.update_wav_profile_ui()

    # --- LOGIC METHODS ---

    def update_slider_label(self, value):
        self.echo_label.config(text=f"DELAY: {int(float(value))}ms")

    def get_wav_profile(self):
        return WAV_PROFILE_LOOP if "Thrust/Turbo" in self.wav_profile_var.get() else WAV_PROFILE_RADIO

    def update_wav_profile_ui(self, event=None):
        is_loop_profile = self.get_wav_profile() == WAV_PROFILE_LOOP
        controls = [
            self.phaser_check,
            self.echo_check,
            self.echo_slider,
            self.beep_dropdown,
            self.intensity_dropdown,
        ]

        for control in controls:
            if is_loop_profile:
                control.state(["disabled"])
            else:
                control.state(["!disabled"])

        if is_loop_profile:
            self.btn_radio.config(text="EXPORT THRUST/TURBO LOOP WAV")
        else:
            self.btn_radio.config(text="INITIATE WAV PROCESSING")

    def log(self, text, tag=None):
        self.log_box.config(state="normal")
        ts = datetime.now().strftime("[%H:%M:%S] ")
        self.log_box.insert("end", ts, "timestamp")
        self.log_box.insert("end", text + "\n", tag)
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def check_custom_beep(self, event=None):
        choice = self.beep_var.get()
        if choice == "Custom...":
            path = filedialog.askopenfilename(title="Select Custom Beep WAV", filetypes=[("WAV files", "*.wav")])
            if path:
                self.custom_beep_path = path
                self.log(f"Custom beep loaded: {os.path.basename(path)}", "success")
            else:
                self.beep_var.set("None")

    def get_input_list(self):
        if self.process_mode.get() == "single":
            path = filedialog.askopenfilename(title="Select Audio File", filetypes=[("Audio Files", " ".join("*" + e for e in processing.INPUT_EXTENSIONS))])
            return [path] if path else []
        folder = filedialog.askdirectory(title="Select Input Folder")
        return [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(processing.INPUT_EXTENSIONS)] if folder else []

    def start_thread(self, mode):
        files = self.get_input_list()
        if not files: return
        
        # Disable buttons
        self.btn_radio.state(['disabled'])
        self.btn_ogg.state(['disabled'])
        
        threading.Thread(target=self.process_logic, args=(files, mode), daemon=True).start()

    def process_logic(self, files, mode):
        total = len(files)
        wav_profile = self.get_wav_profile() if mode == "wav" else None
        out_subdir = "bz98_radio_export" if mode == "wav" and wav_profile == WAV_PROFILE_RADIO else \
                     "bz98_loop_export" if mode == "wav" else "bz98_music_export"
        out_dir = os.path.join(os.path.dirname(files[0]), out_subdir)
        os.makedirs(out_dir, exist_ok=True)
        
        keep_tags = not self.strip_metadata_var.get()
        settings = None
        if mode == "wav" and wav_profile == WAV_PROFILE_RADIO:
            choice = self.beep_var.get()
            beep = COMM_BEEP if "comm" in choice else \
                   UNIT_BEEP if "unit" in choice else \
                   getattr(self, "custom_beep_path", None) if choice == "Custom..." else None
            settings = processing.RadioSettings(
                intensity=self.intensity_var.get(), phaser=self.phaser_var.get(), echo=self.echo_var.get(),
                echo_delay_ms=int(self.echo_delay_var.get()), beep_path=beep)

        for index, f in enumerate(files):
            # Update Progress
            prog = (index + 1) / total * 100
            self.progress['value'] = prog
            self.status_label.config(text=f"PROCESSING {index+1}/{total}: {os.path.basename(f)}")
            self.update_idletasks()

            out_ext = ".wav" if mode == "wav" else ".ogg"
            out_f = os.path.join(out_dir, os.path.splitext(os.path.basename(f))[0] + out_ext)
            try:
                if mode == "wav" and wav_profile == WAV_PROFILE_LOOP:
                    processing.engine_loop(f, out_f)
                elif mode == "wav":
                    processing.radio_vo(f, out_f, settings)
                else:
                    processing.music_ogg(f, out_f, keep_tags=keep_tags)
                self.log(f"Exported: {os.path.basename(out_f)}", "success")
            except Exception as e:
                self.log(f"Error processing {os.path.basename(f)}: {e}", "error")

        # Completion
        self.status_label.config(text="OPERATION COMPLETE")
        self.btn_radio.state(['!disabled'])
        self.btn_ogg.state(['!disabled'])
        messagebox.showinfo("Success", f"Successfully processed {total} files.")

    def export_csv(self):
        folder = filedialog.askdirectory(title="Select folder containing converted audio")
        if not folder: return
        save_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV File", "*.csv")], initialfile="audio_manifest.csv")
        if not save_path: return
        
        with open(save_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Filename", "Duration", "Type"])
            count = 0
            for file in os.listdir(folder):
                if file.lower().endswith(('.wav', '.ogg')):
                    try:
                        seconds = processing.duration(os.path.join(folder, file))
                        writer.writerow([file, round(seconds, 3), "OGG" if file.endswith(".ogg") else "WAV"])
                        count += 1
                    except: continue
        self.log(f"Manifest exported with {count} entries to: {save_path}", "success")

if __name__ == "__main__":
    app = BZRadio()
    app.mainloop()
