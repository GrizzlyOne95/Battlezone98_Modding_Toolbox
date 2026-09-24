import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
from deep_translator import GoogleTranslator
from deep_translator.exceptions import TooManyRequests
import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest
import requests
import json
import time
import threading
import os
import ctypes
import re
import sys

# Platform check
IS_WINDOWS = sys.platform == "win32"

LOCALIZATION_HEADER = b"Key~English~French~German~Spanish~Italian~Russian~Portuguese"
LOCALIZATION_COLUMN_NAMES = (
    "Key", "English", "French", "German", "Spanish", "Italian", "Russian", "Portuguese"
)
# The stock Battlezone 98 Redux localization_table.csv is a mixed-codepage table:
# Western-language columns are Windows-1252 while Russian is Windows-1251.
LOCALIZATION_ENCODINGS = (
    "cp1252", "cp1252", "cp1252", "cp1252", "cp1252", "cp1252", "cp1251", "cp1252"
)


class TranslationRateLimitError(RuntimeError):
    """Raised when the free translation provider remains throttled after backoff."""


class CloudTranslationError(RuntimeError):
    """Raised when Google Cloud Translation configuration or a batch request fails."""


class FreeTranslationError(RuntimeError):
    """Raised when the credential-free Google HTTP translation path fails."""


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

class BZ98GuiApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Battlezone 98 Redux - Localization Tool")
        self.root.geometry("900x1030")
        
        # Colors (Matched to Workshop Uploader)
        self.colors = {
            "bg": "#0a0a0a", "fg": "#d4d4d4",
            "highlight": "#00ff00", "dark_highlight": "#004400", "accent": "#00ffff"
        }
        self.root.configure(bg=self.colors["bg"])

        # Default Paths
        self.paths = {
            "steam": r"C:\Program Files (x86)\Steam\steamapps\common\Battlezone 98 Redux\localization_table.csv",
            "gog": r"C:\GOG Games\Battlezone 98 Redux\localization_table.csv"
        }
        
        self.csv_path = tk.StringVar(value=self.paths["steam"])
        self.scan_folder_path = tk.StringVar()
        self.languages = ['French', 'German', 'Spanish', 'Italian', 'Russian', 'Portuguese']
        self.lang_codes = {'French': 'fr', 'German': 'de', 'Spanish': 'es', 'Italian': 'it', 'Russian': 'ru', 'Portuguese': 'pt'}
        self._translator_cache = {}
        self._last_translation_request = 0.0
        self._translation_min_interval = 0.4
        self.bulk_translation_backend = tk.StringVar(value="Free HTTP (no account)")
        self.google_project_id = tk.StringVar(
            value=os.environ.get("GOOGLE_CLOUD_PROJECT", "")
            or os.environ.get("GCLOUD_PROJECT", "")
        )
        self.google_credentials_path = tk.StringVar(
            value=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        )

        self.load_custom_font()
        self.setup_styles()
        self.setup_ui()

    def load_custom_font(self):
        self.main_font = "Consolas"
        self.header_font = "Consolas"
        
        base_path = os.path.dirname(os.path.abspath(__file__))

        if IS_WINDOWS:
            font_path = os.path.join(base_path, "BZONE.ttf")
            if os.path.exists(font_path):
                try:
                    if ctypes.windll.gdi32.AddFontResourceExW(font_path, 0x10, 0) > 0:
                        self.header_font = "BZONE"
                except: pass

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('default')
        c = self.colors
        
        style.configure(".", background=c["bg"], foreground=c["fg"], font=(self.main_font, 10))
        style.configure("TFrame", background=c["bg"])
        style.configure("TNotebook", background=c["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background="#1a1a1a", foreground=c["fg"], padding=[15, 5])
        style.map("TNotebook.Tab", background=[("selected", c["dark_highlight"])], foreground=[("selected", c["highlight"])])
        
        style.configure("TLabelframe", background=c["bg"], bordercolor=c["highlight"])
        style.configure("TLabelframe.Label", background=c["bg"], foreground=c["highlight"], font=(self.header_font, 11, "bold"))
        
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        style.configure("Header.TLabel", foreground=c["highlight"], font=(self.header_font, 20, "bold"))
        
        style.configure("TButton", background="#1a1a1a", foreground=c["fg"], padding=5)
        style.map("TButton", background=[("active", c["dark_highlight"])], foreground=[("active", c["highlight"])])
        
        style.configure("Primary.TButton", background=c["dark_highlight"], foreground=c["highlight"], font=(self.header_font, 12, "bold"))
        
        style.configure("TEntry", fieldbackground="#1a1a1a", foreground=c["accent"], insertcolor=c["highlight"])
        style.configure("TProgressbar", thickness=20, trowcolor=c["dark_highlight"], background=c["highlight"])

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill="both", expand=True)

        # Header
        header_label = ttk.Label(main_frame, text="LOCALIZATION TOOL", style="Header.TLabel")
        header_label.pack(pady=(0, 20))

        # CSV Path Config
        path_frame = ttk.LabelFrame(main_frame, text=" TARGET LOCALIZATION TABLE ", padding=10)
        path_frame.pack(fill="x", pady=(0, 10))
        
        jump_frame = ttk.Frame(path_frame)
        jump_frame.pack(fill="x", pady=(0, 5))
        ttk.Button(jump_frame, text="STEAM DEFAULT", command=lambda: self.set_preset_path("steam")).pack(side="left", padx=2)
        ttk.Button(jump_frame, text="GOG DEFAULT", command=lambda: self.set_preset_path("gog")).pack(side="left", padx=2)
        
        path_sub = ttk.Frame(path_frame)
        path_sub.pack(fill="x")
        ttk.Entry(path_sub, textvariable=self.csv_path).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(path_sub, text="BROWSE", command=self.browse_csv).pack(side="right")

        # ODF bulk translation backend selection.
        cloud_frame = ttk.LabelFrame(
            main_frame, text=" TRANSLATION BACKEND (ODF BULK) ", padding=10
        )
        cloud_frame.pack(fill="x", pady=(0, 10))
        cloud_frame.columnconfigure(1, weight=1)

        ttk.Label(cloud_frame, text="Backend:").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=2
        )
        backend_combo = ttk.Combobox(
            cloud_frame,
            textvariable=self.bulk_translation_backend,
            values=["Free HTTP (no account)", "Google Cloud v3"],
            state="readonly",
        )
        backend_combo.grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)

        ttk.Label(cloud_frame, text="Cloud Project ID:").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=2
        )
        ttk.Entry(cloud_frame, textvariable=self.google_project_id).grid(
            row=1, column=1, columnspan=2, sticky="ew", pady=2
        )

        ttk.Label(cloud_frame, text="Cloud Credentials JSON:").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=2
        )
        ttk.Entry(cloud_frame, textvariable=self.google_credentials_path).grid(
            row=2, column=1, sticky="ew", pady=2
        )
        ttk.Button(
            cloud_frame, text="BROWSE", command=self.browse_google_credentials
        ).grid(row=2, column=2, padx=(5, 0), pady=2)

        ttk.Label(
            cloud_frame,
            text=(
                "Free HTTP is the default: it joins many unit names into each "
                "request and needs no account or billing. Google Cloud v3 remains "
                "available as the official authenticated option. Manual Translate "
                "still uses deep-translator."
            ),
            wraplength=800,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(5, 0))

        # Tabs
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill="both", expand=True)

        self.manual_tab = ttk.Frame(self.notebook, padding=10)
        self.odf_tab = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(self.manual_tab, text=" MANUAL TRANSLATE ")
        self.notebook.add(self.odf_tab, text=" ODF SCANNER ")

        self.setup_manual_tab()
        self.setup_odf_tab()

        # Shared Activity Log
        log_frame = ttk.LabelFrame(main_frame, text=" ACTIVITY LOG ", padding=10)
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        
        self.log_area = scrolledtext.ScrolledText(log_frame, height=10, bg="#050505", fg=self.colors["fg"], 
                                                 font=("Consolas", 10), insertbackground=self.colors["highlight"])
        self.log_area.pack(fill="both", expand=True)
        self.log_area.configure(state='disabled')

        # Progress Bar
        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.pack(fill="x", pady=(10, 0))

    def setup_manual_tab(self):
        ttk.Label(self.manual_tab, text="Paste English text (one per line):").pack(anchor="w")
        self.text_input = scrolledtext.ScrolledText(self.manual_tab, height=15, bg="#1a1a1a", fg=self.colors["accent"], 
                                                   font=("Consolas", 11), insertbackground=self.colors["highlight"])
        self.text_input.pack(fill="both", expand=True, pady=5)
        
        btn_run = ttk.Button(self.manual_tab, text="TRANSLATE & APPEND", style="Primary.TButton", command=self.start_manual_thread)
        btn_run.pack(pady=10, ipady=5, fill="x")
        self.btn_run = btn_run

    def setup_odf_tab(self):
        scan_frame = ttk.Frame(self.odf_tab)
        scan_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(scan_frame, text="Source Folder:").pack(side="left")
        ttk.Entry(scan_frame, textvariable=self.scan_folder_path).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(scan_frame, text="BROWSE", command=self.browse_scan_folder).pack(side="left")
        
        ttk.Button(self.odf_tab, text="SCAN FOLDER FOR ODFs", command=self.start_scan_thread).pack(fill="x", pady=5)
        
        # Results List
        res_frame = ttk.LabelFrame(self.odf_tab, text=" DISCOVERED UNITS ", padding=5)
        res_frame.pack(fill="both", expand=True)
        
        self.odf_list = tk.Listbox(res_frame, bg="#1a1a1a", fg=self.colors["accent"], selectbackground=self.colors["dark_highlight"], 
                                   selectforeground=self.colors["highlight"], font=("Consolas", 10), borderwidth=0)
        self.odf_list.pack(side="left", fill="both", expand=True)
        
        sb = ttk.Scrollbar(res_frame, orient="vertical", command=self.odf_list.yview)
        sb.pack(side="right", fill="y")
        self.odf_list.config(yscrollcommand=sb.set)
        
        self.btn_bulk = ttk.Button(self.odf_tab, text="COLLECT & TRANSLATE ALL", style="Primary.TButton", command=self.start_bulk_thread, state="disabled")
        self.btn_bulk.pack(pady=10, ipady=5, fill="x")

    def log(self, message):
        self.log_area.configure(state='normal')
        self.log_area.insert(tk.END, f"> {message}\n")
        self.log_area.see(tk.END)
        self.log_area.configure(state='disabled')
        self.root.update_idletasks()

    def set_preset_path(self, version):
        self.csv_path.set(self.paths[version])
        self.log(f"Path set to {version.upper()} default.")

    def browse_csv(self):
        f = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if f: self.csv_path.set(f)

    def browse_scan_folder(self):
        d = filedialog.askdirectory()
        if d: self.scan_folder_path.set(d)

    def browse_google_credentials(self):
        f = filedialog.askopenfilename(
            filetypes=[("Google credentials", "*.json"), ("All Files", "*.*")]
        )
        if f:
            self.google_credentials_path.set(f)

    def get_existing_keys(self):
        """Read localization keys without decoding the translated columns.

        Battlezone localization tables in the wild are not consistently UTF-8.
        Keys are stored before the first '~', so reading only that byte slice
        avoids failing on legacy ANSI/code-page bytes elsewhere in the row.
        """
        keys = set()
        path = self.csv_path.get()

        if not os.path.exists(path):
            return keys

        try:
            with open(path, 'rb') as f:
                for raw_line in f:
                    raw_key = raw_line.split(b'~', 1)[0].strip()
                    if not raw_key:
                        continue

                    try:
                        key = raw_key.decode('utf-8-sig')
                    except UnicodeDecodeError:
                        key = raw_key.decode('cp1252', errors='replace')

                    key = key.strip()
                    if key:
                        keys.add(key)
        except Exception as e:
            self.log(f"Error reading existing keys: {e}")

        return keys

    @staticmethod
    def make_names_key(display_name):
        """Return the exact stock lookup key for a player-visible name."""
        display_name = str(display_name or "").strip()
        if not display_name:
            raise ValueError("Cannot create a localization key from an empty name.")
        if any(ch in display_name for ch in ("~", "\r", "\n")):
            raise ValueError(
                "Localization names cannot contain '~' or line breaks because "
                "Battlezone uses '~' as the field delimiter."
            )
        return f"names:{display_name}"

    def validate_target_table_format(self):
        """Verify that the selected file is a Battlezone localization table."""
        path = self.csv_path.get()
        if not os.path.exists(path):
            raise ValueError("Target localization table does not exist.")

        with open(path, "rb") as f:
            first_line = f.readline()

        first_line = first_line.rstrip(b"\r\n")
        if first_line.startswith(b"\xef\xbb\xbf"):
            first_line = first_line[3:]

        if first_line != LOCALIZATION_HEADER:
            raise ValueError(
                "Target file does not have the expected Battlezone localization "
                "header: Key~English~French~German~Spanish~Italian~Russian~Portuguese"
            )

    @staticmethod
    def _encode_localization_row(row):
        """Encode one row exactly like the stock Battlezone localization table."""
        if len(row) != len(LOCALIZATION_ENCODINGS):
            raise ValueError(
                f"Localization rows must contain exactly 8 fields; got {len(row)}."
            )

        encoded_fields = []
        for column_name, value, encoding in zip(
            LOCALIZATION_COLUMN_NAMES, row, LOCALIZATION_ENCODINGS
        ):
            text = str(value)
            if any(ch in text for ch in ("~", "\r", "\n")):
                raise ValueError(
                    f"{column_name} contains '~' or a line break, which cannot be "
                    "stored safely in Battlezone's tilde-delimited table."
                )
            try:
                encoded_fields.append(text.encode(encoding, errors="strict"))
            except UnicodeEncodeError as e:
                bad = text[e.start:e.end]
                raise ValueError(
                    f"{column_name} contains character(s) {bad!r} that are not "
                    f"representable in the stock {encoding} localization column."
                ) from e

        return b"~".join(encoded_fields) + b"\r\n"

    @staticmethod
    def _ensure_append_boundary(file_handle):
        """Ensure the next binary row starts on a fresh line."""
        file_handle.seek(0, os.SEEK_END)
        size = file_handle.tell()
        if not size:
            return

        file_handle.seek(-1, os.SEEK_END)
        last = file_handle.read(1)
        if last != b"\n":
            file_handle.seek(0, os.SEEK_END)
            file_handle.write(b"\r\n")

    def _write_localization_row(self, file_handle, row):
        file_handle.write(self._encode_localization_row(row))

    def _get_string_setting(self, attribute_name):
        value = getattr(self, attribute_name, "")
        if hasattr(value, "get"):
            value = value.get()
        return str(value or "").strip()

    @staticmethod
    def _chunk_free_http_contents(texts, max_chars=4500):
        """Chunk newline-delimited text conservatively for the unofficial endpoint."""
        chunks = []
        current = []
        current_chars = 0

        for text in texts:
            text_chars = len(text)
            if text_chars > max_chars:
                raise FreeTranslationError(
                    "A single source string is too long for the free HTTP translator."
                )

            added = text_chars + (1 if current else 0)
            if current and current_chars + added > max_chars:
                chunks.append(current)
                current = []
                current_chars = 0
                added = text_chars

            current.append(text)
            current_chars += added

        if current:
            chunks.append(current)

        return chunks

    @staticmethod
    def _extract_free_http_translation(payload):
        """Normalize common unauthenticated Google translation response shapes."""
        if isinstance(payload, dict):
            sentences = payload.get("sentences")
            if isinstance(sentences, list):
                return "".join(
                    str(sentence.get("trans", ""))
                    for sentence in sentences
                    if isinstance(sentence, dict)
                )

        if isinstance(payload, list) and payload:
            if all(isinstance(item, str) for item in payload):
                return "\n".join(payload)

            first = payload[0]
            if isinstance(first, list):
                pieces = []
                for sentence in first:
                    if (
                        isinstance(sentence, list)
                        and sentence
                        and isinstance(sentence[0], str)
                    ):
                        pieces.append(sentence[0])
                if pieces:
                    return "".join(pieces)

                try:
                    nested = first[0][0][0][0]
                    if isinstance(nested, list):
                        return "".join(str(piece) for piece in nested)
                except (IndexError, TypeError):
                    pass

        return ""

    @staticmethod
    def _parse_marker_translation(translated_blob, expected_count):
        """Recover per-line output if Google rewrites newline boundaries."""
        marker_re = re.compile(r"\[\[\s*BZ\s*(\d+)\s*\]\]", re.IGNORECASE)
        matches = list(marker_re.finditer(translated_blob))
        if len(matches) != expected_count:
            return None

        results = []
        for index, match in enumerate(matches):
            try:
                marker_index = int(match.group(1))
            except (TypeError, ValueError):
                return None

            if marker_index != index:
                return None

            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(translated_blob)
            value = translated_blob[start:end].strip(" \t\r\n:-")
            if not value:
                return None
            results.append(value)

        return results

    @staticmethod
    def _short_http_error(response):
        """Return a useful HTTP error without dumping Google's HTML block page."""
        status = getattr(response, "status_code", "?")
        if status == 429:
            return "HTTP 429: Google rejected this endpoint for this IP/network."
        if status == 403:
            return "HTTP 403: Google rejected this endpoint for this request."

        try:
            payload = response.json()
        except (ValueError, TypeError):
            payload = None

        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = str(error.get("message", "")).strip()
                if message:
                    return f"HTTP {status}: {message}"

        text = re.sub(r"<[^>]+>", " ", str(getattr(response, "text", "")))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 180:
            text = text[:177] + "..."
        return f"HTTP {status}: {text or 'no error details returned'}"

    @staticmethod
    def _parse_google_rpc_response(response_text):
        """Parse Google Translate's MkEWBc batchexecute response into plain text."""
        token_found = False
        assembled = ""
        opening_bracket = 0
        closing_bracket = 0

        for line in str(response_text).split("\n"):
            token_found = token_found or '"MkEWBc"' in line[:80]
            if not token_found:
                continue

            in_string = False
            escaped = False
            for char in line:
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if char == "[":
                        opening_bracket += 1
                    elif char == "]":
                        closing_bracket += 1

            assembled += line
            if opening_bracket and opening_bracket == closing_bracket:
                break

        if not assembled:
            raise FreeTranslationError(
                "Google Translate web RPC returned an unrecognized response."
            )

        try:
            envelope = json.loads(assembled)
            inner = json.loads(envelope[0][2])
            segment = inner[1][0][0]
            separator = " " if segment[3] else ""
            translated = separator.join(
                str(part[0])
                for part in segment[5]
                if isinstance(part, list) and part and part[0] is not None
            )
        except (ValueError, TypeError, IndexError, KeyError) as e:
            raise FreeTranslationError(
                f"Google Translate web RPC response could not be parsed: {e}"
            ) from e

        if not translated.strip():
            raise FreeTranslationError(
                "Google Translate web RPC returned an empty translation."
            )
        return translated.strip()

    def _request_free_rpc_translation(self, source_text, target):
        endpoint = "https://translate.google.com/_/TranslateWebserverUi/data/batchexecute"
        rpc_payload = json.dumps(
            [[source_text, "en", target, True], [None]],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        rpc_request = json.dumps(
            [[["MkEWBc", rpc_payload, None, "generic"]]],
            separators=(",", ":"),
            ensure_ascii=False,
        )

        try:
            response = requests.post(
                endpoint,
                params={
                    "rpcids": "MkEWBc",
                    "bl": "boq_translate-webserver_20201207.13_p0",
                    "soc-app": "1",
                    "soc-platform": "1",
                    "soc-device": "1",
                    "rt": "c",
                },
                data={"f.req": rpc_request},
                headers={
                    "Accept": "*/*",
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    "Origin": "https://translate.google.com",
                    "Referer": "https://translate.google.com/",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/140.0.0.0 Safari/537.36"
                    ),
                },
                timeout=45,
            )
        except requests.RequestException as e:
            raise FreeTranslationError(
                f"Google Translate web RPC connection failed: {e}"
            ) from e

        if response.status_code >= 400:
            raise FreeTranslationError(
                "Google Translate web RPC failed: "
                + self._short_http_error(response)
            )

        return self._parse_google_rpc_response(response.text)

    def _request_free_clients5_translation(self, source_text, target):
        endpoint = "https://clients5.google.com/translate_a/t"
        try:
            response = requests.get(
                endpoint,
                params={
                    "client": "dict-chrome-ex",
                    "sl": "en",
                    "tl": target,
                    "q": source_text,
                },
                headers={
                    "Accept": "application/json,text/plain,*/*",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/140.0.0.0 Safari/537.36"
                    ),
                },
                timeout=45,
            )
        except requests.RequestException as e:
            raise FreeTranslationError(
                f"Google Chrome-extension translation endpoint failed to connect: {e}"
            ) from e

        if response.status_code >= 400:
            raise FreeTranslationError(
                "Google Chrome-extension translation endpoint failed: "
                + self._short_http_error(response)
            )

        try:
            payload = response.json()
        except ValueError as e:
            raise FreeTranslationError(
                "Google Chrome-extension translation endpoint returned invalid JSON."
            ) from e

        translated = self._extract_free_http_translation(payload)
        if not translated.strip():
            raise FreeTranslationError(
                "Google Chrome-extension translation endpoint returned no translation text."
            )
        return translated

    def _request_free_legacy_translation(self, source_text, target):
        endpoint = "https://translate.googleapis.com/translate_a/single"
        try:
            response = requests.post(
                endpoint,
                params={
                    "client": "gtx",
                    "sl": "en",
                    "tl": target,
                    "dt": "t",
                    "dj": "1",
                },
                data={"q": source_text},
                headers={
                    "Accept": "application/json",
                    "User-Agent": "BZLocalizationTool/2.x",
                },
                timeout=45,
            )
        except requests.RequestException as e:
            raise FreeTranslationError(
                f"Legacy Google translation endpoint failed to connect: {e}"
            ) from e

        if response.status_code >= 400:
            raise FreeTranslationError(
                "Legacy Google translation endpoint failed: "
                + self._short_http_error(response)
            )

        try:
            payload = response.json()
        except ValueError as e:
            raise FreeTranslationError(
                "Legacy Google translation endpoint returned invalid JSON."
            ) from e

        translated = self._extract_free_http_translation(payload)
        if not translated.strip():
            raise FreeTranslationError(
                "Legacy Google translation endpoint returned no translation text."
            )
        return translated

    def _request_free_http_translation(self, source_text, target):
        """Try several credential-free Google routes without retrying one blocked route."""
        providers = [
            ("web RPC", self._request_free_rpc_translation),
            ("Chrome-extension endpoint", self._request_free_clients5_translation),
            ("legacy endpoint", self._request_free_legacy_translation),
        ]
        failures = []

        for provider_name, provider in providers:
            try:
                translated = provider(source_text, target)
                if failures:
                    self.log(
                        f"Free translator fallback succeeded via {provider_name}."
                    )
                return translated
            except FreeTranslationError as e:
                failures.append(f"{provider_name}: {e}")
                self.log(f"Free translator {provider_name} unavailable; trying fallback.")

        summary = " | ".join(failures)
        if len(summary) > 700:
            summary = summary[:697] + "..."
        raise FreeTranslationError(
            "All credential-free Google translation routes failed. " + summary
        )

    def _translate_free_http_chunk(self, chunk, target):
        """Translate a chunk in one request, retrying with markers only if needed."""
        source_text = "\n".join(chunk)
        translated_blob = self._request_free_http_translation(source_text, target)
        normalized = translated_blob.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.strip() for line in normalized.split("\n")]

        while lines and not lines[-1]:
            lines.pop()

        if len(lines) == len(chunk) and all(lines):
            return lines

        marked_source = "\n".join(
            f"[[BZ{index}]] {text}" for index, text in enumerate(chunk)
        )
        marked_blob = self._request_free_http_translation(marked_source, target)
        parsed = self._parse_marker_translation(marked_blob, len(chunk))
        if parsed is None:
            raise FreeTranslationError(
                "Google returned translated text, but the unit-name boundaries "
                "could not be mapped safely. No localization rows were written."
            )
        return parsed

    def translate_batch_free_http(self, english_texts):
        """Translate many names with a tiny number of credential-free HTTP requests."""
        texts = [str(text).strip() for text in english_texts]
        if not texts:
            return []
        if any(not text for text in texts):
            raise FreeTranslationError("Free HTTP batch contains an empty source string.")
        if any("\n" in text or "\r" in text for text in texts):
            raise FreeTranslationError(
                "Unit names containing line breaks are not supported by the free "
                "batched translator."
            )

        chunks = self._chunk_free_http_contents(texts)
        request_count = len(chunks) * len(self.languages)
        self.log(
            f"Free HTTP batch translation: {len(texts)} strings, "
            f"{len(self.languages)} languages, about {request_count} request(s)."
        )

        translated_by_language = []
        for lang_index, lang in enumerate(self.languages, start=1):
            target = self.lang_codes[lang]
            translated_texts = []

            for chunk_index, chunk in enumerate(chunks, start=1):
                self.log(
                    f"Free HTTP: {lang} ({lang_index}/{len(self.languages)}), "
                    f"batch {chunk_index}/{len(chunks)} with {len(chunk)} strings..."
                )
                translated_texts.extend(
                    self._translate_free_http_chunk(chunk, target)
                )

            translated_by_language.append(translated_texts)

        return [
            [
                translated_by_language[lang_index][text_index]
                for lang_index in range(len(self.languages))
            ]
            for text_index in range(len(texts))
        ]

    def _load_cloud_credentials(self):
        """Resolve Google Cloud credentials and the billing/project identifier."""
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        credentials_path = self._get_string_setting("google_credentials_path")
        project_id = (
            self._get_string_setting("google_project_id")
            or os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
            or os.environ.get("GCLOUD_PROJECT", "").strip()
        )

        try:
            if credentials_path:
                if not os.path.isfile(credentials_path):
                    raise CloudTranslationError(
                        f"Google credentials file not found: {credentials_path}"
                    )
                credentials, detected_project = google.auth.load_credentials_from_file(
                    credentials_path, scopes=scopes
                )
            else:
                credentials, detected_project = google.auth.default(scopes=scopes)
        except CloudTranslationError:
            raise
        except Exception as e:
            raise CloudTranslationError(
                "Google Cloud credentials are not configured. Select a service "
                "account JSON file (or configure Application Default Credentials) "
                f"and try again. Details: {e}"
            ) from e

        project_id = project_id or detected_project or getattr(
            credentials, "project_id", None
        )
        if not project_id:
            raise CloudTranslationError(
                "Google Cloud Project ID is required. Enter it in the ODF Bulk "
                "Google Cloud section or set GOOGLE_CLOUD_PROJECT."
            )

        try:
            if not credentials.valid:
                credentials.refresh(GoogleAuthRequest())
        except Exception as e:
            raise CloudTranslationError(
                f"Could not authenticate to Google Cloud Translation: {e}"
            ) from e

        if not getattr(credentials, "token", None):
            raise CloudTranslationError(
                "Google Cloud authentication completed without an access token."
            )

        return str(project_id).strip(), credentials

    @staticmethod
    def _chunk_cloud_contents(texts, max_codepoints=30000, max_items=1024):
        """Keep normal ODF scans to one request while respecting v3 hard limits."""
        chunks = []
        current = []
        current_codepoints = 0

        for text in texts:
            text_codepoints = len(text)
            if text_codepoints > max_codepoints:
                raise CloudTranslationError(
                    "A single source string exceeds Google Cloud Translation's "
                    f"{max_codepoints:,}-codepoint synchronous request limit."
                )

            if current and (
                len(current) >= max_items
                or current_codepoints + text_codepoints > max_codepoints
            ):
                chunks.append(current)
                current = []
                current_codepoints = 0

            current.append(text)
            current_codepoints += text_codepoints

        if current:
            chunks.append(current)

        return chunks

    def translate_batch_cloud(self, english_texts):
        """Translate many source strings with one v3 request per language when possible."""
        texts = [str(text).strip() for text in english_texts]
        if not texts:
            return []
        if any(not text for text in texts):
            raise CloudTranslationError("Google Cloud batch contains an empty source string.")

        chunks = self._chunk_cloud_contents(texts)
        project_id, credentials = self._load_cloud_credentials()
        endpoint = (
            "https://translation.googleapis.com/v3/projects/"
            f"{project_id}:translateText"
        )
        request_count = len(chunks) * len(self.languages)
        self.log(
            f"Google Cloud batch translation: {len(texts)} strings, "
            f"{len(self.languages)} languages, {request_count} API request(s)."
        )

        translated_by_language = []
        for lang_index, lang in enumerate(self.languages, start=1):
            target = self.lang_codes[lang]
            translated_texts = []

            for chunk_index, chunk in enumerate(chunks, start=1):
                self.log(
                    f"Google Cloud: {lang} ({lang_index}/{len(self.languages)}), "
                    f"batch {chunk_index}/{len(chunks)} with {len(chunk)} strings..."
                )
                try:
                    response = requests.post(
                        endpoint,
                        headers={
                            "Authorization": f"Bearer {credentials.token}",
                            "x-goog-user-project": project_id,
                            "Content-Type": "application/json; charset=utf-8",
                        },
                        json={
                            "sourceLanguageCode": "en",
                            "targetLanguageCode": target,
                            "mimeType": "text/plain",
                            "contents": chunk,
                        },
                        timeout=90,
                    )
                except requests.RequestException as e:
                    raise CloudTranslationError(
                        f"{lang} request could not reach Google Cloud Translation: {e}"
                    ) from e

                try:
                    payload = response.json()
                except ValueError:
                    payload = {}

                if response.status_code >= 400:
                    detail = ""
                    if isinstance(payload, dict):
                        error = payload.get("error", {})
                        if isinstance(error, dict):
                            detail = str(error.get("message", "")).strip()
                    if not detail:
                        detail = str(getattr(response, "text", "")).strip()
                    if not detail:
                        detail = "No error details returned."
                    raise CloudTranslationError(
                        f"{lang} Google Cloud request failed (HTTP "
                        f"{response.status_code}): {detail}"
                    )

                translations = payload.get("translations") if isinstance(payload, dict) else None
                if not isinstance(translations, list) or len(translations) != len(chunk):
                    raise CloudTranslationError(
                        f"{lang} returned {0 if not isinstance(translations, list) else len(translations)} "
                        f"translations for {len(chunk)} source strings."
                    )

                batch_results = []
                for item in translations:
                    translated = (
                        str(item.get("translatedText", "")).strip()
                        if isinstance(item, dict)
                        else ""
                    )
                    if not translated:
                        raise CloudTranslationError(
                            f"{lang} returned an empty translation in the batch."
                        )
                    batch_results.append(translated)

                translated_texts.extend(batch_results)

            translated_by_language.append(translated_texts)

        return [
            [translated_by_language[lang_index][text_index]
             for lang_index in range(len(self.languages))]
            for text_index in range(len(texts))
        ]

    def _get_translator(self, target):
        cache = getattr(self, '_translator_cache', None)
        if cache is None:
            cache = {}
            self._translator_cache = cache

        translator = cache.get(target)
        if translator is None:
            translator = GoogleTranslator(source='en', target=target)
            cache[target] = translator
        return translator

    def _wait_for_translation_slot(self):
        min_interval = getattr(self, '_translation_min_interval', 0.4)
        last_request = getattr(self, '_last_translation_request', 0.0)
        now = time.monotonic()
        remaining = min_interval - (now - last_request)

        if remaining > 0:
            time.sleep(remaining)

        self._last_translation_request = time.monotonic()

    @staticmethod
    def _is_rate_limit_error(error):
        if isinstance(error, TooManyRequests):
            return True

        message = str(error).lower()
        return "too many requests" in message or "429" in message

    def _translate_one(self, english_text, lang, retries=4):
        target = self.lang_codes[lang]
        translator = self._get_translator(target)
        last_error = None

        # A 429 usually means Google's anonymous endpoint has temporarily
        # throttled this IP. Sub-second retries only make that worse.
        rate_limit_cooldowns = [15, 30, 60]
        transient_cooldowns = [1, 2, 4]

        for attempt in range(1, retries + 1):
            try:
                self._wait_for_translation_slot()
                translated = translator.translate(english_text)

                if translated is None or not str(translated).strip():
                    raise RuntimeError("translator returned an empty result")

                return str(translated).strip()
            except Exception as e:
                last_error = e
                self.log(
                    f"Translation error ({lang}, attempt {attempt}/{retries}) "
                    f"for '{english_text}': {e}"
                )

                if attempt >= retries:
                    break

                if self._is_rate_limit_error(e):
                    cooldown = rate_limit_cooldowns[
                        min(attempt - 1, len(rate_limit_cooldowns) - 1)
                    ]
                    self.log(
                        f"Google rate limit detected. Cooling down for "
                        f"{cooldown} seconds before retrying..."
                    )
                else:
                    cooldown = transient_cooldowns[
                        min(attempt - 1, len(transient_cooldowns) - 1)
                    ]

                time.sleep(cooldown)

        message = (
            f"{lang} translation failed for '{english_text}' after "
            f"{retries} attempts: {last_error}"
        )
        if self._is_rate_limit_error(last_error):
            raise TranslationRateLimitError(message)
        raise RuntimeError(message)

    def translate_text(self, english_text, retries=4):
        """Translate one display string into every configured target language."""
        translations = []

        for lang in self.languages:
            translations.append(
                self._translate_one(english_text, lang, retries=retries)
            )

        return translations

    def start_manual_thread(self):
        if not os.path.exists(self.csv_path.get()):
            messagebox.showerror("Error", "Target CSV file not found!")
            return
        try:
            self.validate_target_table_format()
        except ValueError as e:
            messagebox.showerror("Localization Table Format Error", str(e))
            return
        threading.Thread(target=self.process_manual, daemon=True).start()

    def process_manual(self):
        raw_text = self.text_input.get("1.0", tk.END).strip()
        if not raw_text:
            return

        lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
        self.btn_run.config(state='disabled')
        self.progress['maximum'] = len(lines)
        self.progress['value'] = 0

        existing_keys = self.get_existing_keys()
        added_count = 0
        failed_count = 0

        try:
            with open(self.csv_path.get(), 'a+b') as f:
                self._ensure_append_boundary(f)
                for line in lines:
                    if "~" in line and ".bzn" in line.lower():
                        key_part, english_text = line.split("~", 1)
                        safe_key = f"mission_title:{key_part.strip()}"
                        english_text = english_text.strip()
                    else:
                        english_text = line
                        safe_key = self.make_names_key(english_text)

                    if safe_key in existing_keys:
                        self.log(f"Skipping (Duplicate): {safe_key}")
                        self.progress['value'] += 1
                        continue

                    self.log(f"Translating: {english_text}...")
                    try:
                        translations = self.translate_text(english_text)
                    except TranslationRateLimitError as e:
                        failed_count += 1
                        self.progress['value'] += 1
                        self.log(
                            f"Google translation is still rate-limited; stopping "
                            f"this batch so it can be resumed later. ({e})"
                        )
                        break
                    except Exception as e:
                        failed_count += 1
                        self.progress['value'] += 1
                        self.log(f"Skipping failed translation: {safe_key} ({e})")
                        continue

                    row = [safe_key, english_text] + translations
                    self._write_localization_row(f, row)
                    existing_keys.add(safe_key)
                    added_count += 1
                    self.progress['value'] += 1

            self.log(
                f"BATCH COMPLETE! Added {added_count} new entries; "
                f"{failed_count} failed."
            )
            messagebox.showinfo(
                "Success",
                f"Added {added_count} entries. Failed translations: {failed_count}."
            )
            self.text_input.delete("1.0", tk.END)
        except Exception as e:
            self.log(f"Critical Error: {e}")
            messagebox.showerror("Error", str(e))

        self.btn_run.config(state='normal')
        self.progress['value'] = 0

    def start_scan_thread(self):
        if not os.path.exists(self.scan_folder_path.get()):
            messagebox.showerror("Error", "Please select a valid folder to scan.")
            return
        threading.Thread(target=self.perform_scan, daemon=True).start()

    def perform_scan(self):
        folder = self.scan_folder_path.get()
        self.log(f"Scanning folder: {folder}")
        self.odf_list.delete(0, tk.END)
        self.discovered_odfs = []  # List of tuples (path, display_name, key)

        odf_count = 0
        skipped_without_display_name = 0
        seen_keys = set()

        for root, _, files in os.walk(folder):
            for file in files:
                if not file.lower().endswith(".odf"):
                    continue

                odf_count += 1
                path = os.path.join(root, file)
                unit_name = self.extract_unit_name(path)

                if not unit_name:
                    skipped_without_display_name += 1
                    continue

                key = self.make_names_key(unit_name)
                if key in seen_keys:
                    continue

                seen_keys.add(key)
                self.discovered_odfs.append((path, unit_name, key))
                self.odf_list.insert(tk.END, f"{unit_name} ({file})")

        self.log(
            f"Scan complete. Found {len(self.discovered_odfs)} player-visible "
            f"unit names in {odf_count} ODF files; skipped "
            f"{skipped_without_display_name} ODFs without unitName."
        )
        self.btn_bulk.config(
            state="normal" if self.discovered_odfs else "disabled"
        )

    def extract_unit_name(self, path):
        """Return only the player-visible unitName value from an ODF.

        Internal filenames and other ODF fields are intentionally ignored.
        """
        try:
            with open(path, 'r', errors='ignore') as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith(("//", ";", "#")):
                        continue

                    # Drop a normal inline ODF comment before parsing the field.
                    line = line.split("//", 1)[0].strip()
                    if "=" not in line:
                        continue

                    field_name, raw_value = line.split("=", 1)
                    if field_name.strip().lower() != "unitname":
                        continue

                    value = raw_value.strip().rstrip(";").strip()
                    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                        value = value[1:-1].strip()

                    return value or None
        except Exception as e:
            self.log(f"Could not read ODF '{path}': {e}")

        return None

    def start_bulk_thread(self):
        if not os.path.exists(self.csv_path.get()):
            messagebox.showerror("Error", "Target CSV file not found!")
            return
        try:
            self.validate_target_table_format()
        except ValueError as e:
            messagebox.showerror("Localization Table Format Error", str(e))
            return
        threading.Thread(target=self.process_bulk, daemon=True).start()

    def process_bulk(self):
        self.btn_bulk.config(state="disabled")
        self.progress['maximum'] = len(self.discovered_odfs)
        self.progress['value'] = 0

        existing_keys = self.get_existing_keys()
        pending = []

        for path, english_text, safe_key in self.discovered_odfs:
            if safe_key in existing_keys:
                self.log(f"Skipping (Duplicate): {safe_key}")
                self.progress['value'] += 1
                continue
            pending.append((path, english_text, safe_key))

        if not pending:
            self.log("BULK SCAN COMPLETE! No untranslated entries were found.")
            messagebox.showinfo("Success", "No untranslated entries were found.")
            self.btn_bulk.config(state="normal")
            self.progress['value'] = 0
            return

        backend = self._get_string_setting("bulk_translation_backend")
        source_texts = [english_text for _, english_text, _ in pending]

        try:
            if backend == "Google Cloud v3":
                self.log(
                    f"Preparing {len(pending)} untranslated names for official "
                    "Google Cloud Translation v3 batching..."
                )
                translated_rows = self.translate_batch_cloud(source_texts)
            else:
                self.log(
                    f"Preparing {len(pending)} untranslated names for the "
                    "credential-free Google HTTP batch translator..."
                )
                translated_rows = self.translate_batch_free_http(source_texts)
        except Exception as e:
            self.log(f"Bulk translation failed; no rows were written. ({e})")
            messagebox.showerror("Translation Error", str(e))
            self.btn_bulk.config(state="normal")
            self.progress['value'] = 0
            return

        added_count = 0
        try:
            with open(self.csv_path.get(), 'a+b') as f:
                self._ensure_append_boundary(f)
                for (_, english_text, safe_key), translations in zip(
                    pending, translated_rows
                ):
                    row = [safe_key, english_text] + translations
                    self._write_localization_row(f, row)
                    existing_keys.add(safe_key)
                    added_count += 1
                    self.progress['value'] += 1

            self.log(
                f"BULK SCAN COMPLETE! Added {added_count} new entries using "
                f"{backend}."
            )
            messagebox.showinfo(
                "Success",
                f"Bulk translation complete. Added {added_count} units."
            )
        except Exception as e:
            self.log(f"Could not append translated rows: {e}")
            messagebox.showerror("Error", str(e))

        self.btn_bulk.config(state="normal")
        self.progress['value'] = 0

if __name__ == "__main__":
    root = tk.Tk()
    app = BZ98GuiApp(root)
    root.mainloop()