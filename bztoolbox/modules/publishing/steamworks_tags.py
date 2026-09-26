import base64
import ctypes
import glob
import json
import os
import re
import struct
import subprocess
import time

# The DLL has to match this process: 64-bit Python can only load
# steam_api64.dll, and Battlezone 98 Redux ships just the 32-bit steam_api.dll.
IS_64BIT = struct.calcsize("P") == 8
STEAM_API_DLL = "steam_api64.dll" if IS_64BIT else "steam_api.dll"

# Runs Steamworks through the game's 32-bit DLL for a 64-bit toolbox (see steamworks_helper.ps1).
HELPER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "steamworks_helper.ps1")

# EItemUpdateStatus, for progress messages.
UPDATE_STATUS = {
    1: "Preparing",
    2: "Preparing content",
    3: "Uploading content",
    4: "Uploading preview",
    5: "Committing changes",
}

# EResult values Steam returns for Workshop submissions, in words.
ERESULT_TEXT = {
    2: "generic failure",
    3: "no connection to Steam",
    8: "invalid parameter (check the title, description length and tags)",
    9: "file not found (content folder or preview image)",
    15: "access denied (the item belongs to another account, or the Workshop legal agreement is not accepted)",
    16: "timed out",
    17: "the Steam account is banned from the Workshop",
    25: "limit exceeded (preview images must be under 1 MB)",
    33: "not logged on",
    44: "the Steam client is not signed in to Steam",
}
UPLOADER_TOOL_FOLDER = "Battlezone 98 Redux - Uploader Tool"


def _powershell_32():
    """The 32-bit Windows PowerShell of a 64-bit Windows, or None."""
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    path = os.path.join(windir, "SysWOW64", "WindowsPowerShell", "v1.0", "powershell.exe")
    return path if os.path.exists(path) else None


def steam_client_running():
    """False when the Steam client is known not to be running and signed in, else True."""
    if os.name != "nt":
        return True
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess") as key:
            user, _ = winreg.QueryValueEx(key, "ActiveUser")
        return bool(user)
    except OSError:
        return True   # cannot tell: let SteamAPI_Init decide


def embedded_interface_version(dll_path, prefix, default=None):
    """The ``<prefix>NNN`` interface version compiled against ``dll_path``.

    The flat API calls methods through the vtable of the SDK the DLL was
    built from, so the interface must be requested at exactly that version.
    Old SDKs compiled the ISteamUGC version into the game, not the DLL, so
    executables beside it are searched too.
    """
    pattern = re.compile(re.escape(prefix.encode("ascii")) + rb"(\d{3})")
    folder = os.path.dirname(dll_path)
    for path in [dll_path] + sorted(glob.glob(os.path.join(folder, "*.exe"))):
        try:
            with open(path, "rb") as f:
                versions = sorted(set(pattern.findall(f.read())))
        except OSError:
            continue
        if versions:
            return prefix + versions[-1].decode("ascii")
    return default


class SteamParamStringArray(ctypes.Structure):
    _fields_ = [
        ("strings", ctypes.POINTER(ctypes.c_char_p)),
        ("num_strings", ctypes.c_int),
    ]


class SubmitItemUpdateResult(ctypes.Structure):
    _fields_ = [
        ("result", ctypes.c_int),
        ("needs_legal_agreement", ctypes.c_bool),
        ("_padding", ctypes.c_ubyte * 3),
        ("published_file_id", ctypes.c_uint64),
    ]


class SteamworksTagUpdater:
    ERESULT_OK = 1
    SUBMIT_ITEM_UPDATE_CALLBACK_ID = 3404
    STEAM_CLIENT_VERSION = b"SteamClient017"
    STEAM_UTILS_VERSION = b"SteamUtils008"
    STEAM_UGC_VERSIONS = [f"STEAMUGC_INTERFACE_VERSION{i:03d}".encode("ascii") for i in range(30, 0, -1)]
    # Flat-API accessors (SDK 1.48+); newer SDKs no longer hand ISteamUGC out
    # through ISteamClient version strings.
    UGC_ACCESSORS = [f"SteamAPI_SteamUGC_v{i:03d}" for i in range(30, 13, -1)]
    UTILS_ACCESSORS = [f"SteamAPI_SteamUtils_v{i:03d}" for i in range(20, 8, -1)]

    def __init__(self, logger=None):
        self.logger = logger

    def log(self, msg):
        if self.logger:
            self.logger(msg)

    def _ensure_appid_file(self, base_dir, appid):
        if not base_dir:
            return None
        path = os.path.join(base_dir, "steam_appid.txt")
        if os.path.exists(path):
            return None
        with open(path, "w", encoding="ascii") as f:
            f.write(str(appid).strip() + "\n")
        return path

    def _candidate_dirs(self, base_dir=None):
        dirs = []
        explicit = os.environ.get("BZ_STEAM_API_DIR", "").strip()
        if explicit:
            dirs.append(explicit)
        if base_dir:
            dirs.append(base_dir)
        dirs.append(os.path.dirname(os.path.abspath(__file__)))

        game_dir = os.environ.get("BZR_GAME_DIR", "").strip()
        if game_dir:
            dirs.append(game_dir)
        try:
            from bztoolbox.settings import Settings

            configured = str(Settings().get("game_dir", "") or "").strip()   # Settings › Game folder
            if configured:
                dirs.append(configured)
        except Exception:
            pass
        try:
            from bztoolbox import external

            for install in external.detect_game_installs():
                dirs.append(str(install))
                # The official uploader tool ships the same steam_api.dll.
                dirs.append(os.path.join(os.path.dirname(str(install)), UPLOADER_TOOL_FOLDER))
        except Exception:
            pass

        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile:
            dirs.append(os.path.join(user_profile, "Documents", "Battlezone 98 Redux"))

        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
        if program_files_x86:
            dirs.append(os.path.join(program_files_x86, "Steam", "steamapps", "common", "Battlezone 98 Redux"))

        dirs.append(os.path.join("C:\\steamcmd", "steamapps", "content", "app_450970", "depot_450971"))
        return dirs

    def find_steam_api_path(self, base_dir=None):
        seen = set()
        for directory in self._candidate_dirs(base_dir):
            norm = os.path.normpath(os.path.join(directory, STEAM_API_DLL))
            if norm in seen:
                continue
            seen.add(norm)
            if os.path.exists(norm):
                return norm
        return None

    def find_32bit_steam_api_path(self, base_dir=None):
        """The game's 32-bit steam_api.dll, which a 64-bit toolbox drives through the helper."""
        if not IS_64BIT:
            return None
        for directory in self._candidate_dirs(base_dir):
            path = os.path.join(directory, "steam_api.dll")
            if os.path.exists(path):
                return os.path.normpath(path)
        return None

    def helper_available(self, base_dir=None):
        """The 32-bit steam_api.dll the helper can drive, or None."""
        if os.name != "nt" or not _powershell_32() or not os.path.exists(HELPER_SCRIPT):
            return None
        return self.find_32bit_steam_api_path(base_dir=base_dir)

    def _run_helper(self, dll_path, appid, publishedfileid, *, init_app_id=None, title="", description="",
                    content="", preview_path="", tags=None, change_note="", visibility=None,
                    timeout_seconds=20, on_progress=None, on_created=None):
        """Run steamworks_helper.ps1 and return its final JSON object; raises on failure."""
        powershell = _powershell_32()
        if not powershell:
            raise RuntimeError("32-bit Windows PowerShell (SysWOW64) was not found.")
        if not os.path.exists(HELPER_SCRIPT):
            raise FileNotFoundError(f"Steamworks helper script is missing: {HELPER_SCRIPT}")

        ugc_version = embedded_interface_version(dll_path, "STEAMUGC_INTERFACE_VERSION")
        if not ugc_version:
            raise RuntimeError(f"Could not tell which ISteamUGC version {dll_path} was built for.")
        utils_version = embedded_interface_version(dll_path, "SteamUtils", default="SteamUtils008")
        user_version = embedded_interface_version(dll_path, "SteamUser", default="SteamUser019")

        def b64(text):
            return base64.b64encode(text.encode("utf-8")).decode("ascii")

        run_as = str(init_app_id or appid)
        cmd = [
            powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", HELPER_SCRIPT,
            "-DllPath", dll_path,
            "-AppId", str(appid),
            "-InitAppId", run_as,
            "-ItemId", str(publishedfileid or 0),
            "-UgcVersion", ugc_version,
            "-UtilsVersion", utils_version,
            "-UserVersion", user_version,
            "-TimeoutSeconds", str(int(timeout_seconds)),
        ]
        # Only non-empty values: Windows PowerShell's -File drops an empty
        # argument, and the flag before it would then swallow the next flag.
        for flag, value in (("-TitleB64", title), ("-DescriptionB64", description),
                            ("-ContentB64", os.path.abspath(content) if content else ""),
                            ("-PreviewB64", os.path.abspath(preview_path) if preview_path else ""),
                            ("-TagsB64", "\n".join(tags or [])), ("-NoteB64", change_note)):
            if value:
                cmd += [flag, b64(value)]
        if visibility is not None and str(visibility).strip() != "":
            cmd += ["-Visibility", str(int(visibility))]
        env = dict(os.environ, SteamAppId=run_as, SteamGameId=run_as)

        self.log(f"Steamworks via 32-bit helper and {dll_path} ({ugc_version}, running as app {run_as})")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        payload = None
        other = []
        deadline = time.time() + timeout_seconds + 90   # PowerShell start-up and the C# compile
        try:
            for raw in proc.stdout:
                line = raw.strip()
                if not line.startswith("{"):
                    if line:
                        other.append(line)
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    other.append(line)
                    continue
                if "progress" in data:
                    if on_progress:
                        on_progress(data["progress"])
                elif "created" in data:
                    if on_created:
                        on_created(str(data["created"]), bool(data.get("needs_legal_agreement")))
                else:
                    payload = data
                if time.time() > deadline:
                    proc.kill()
                    raise TimeoutError("The Steamworks helper did not finish in time.")
            proc.wait(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()

        if payload is None:
            raise RuntimeError(
                f"Steamworks helper exited with code {proc.returncode}" + (f": {other[-1]}" if other else ""))
        if not payload.get("ok"):
            error = payload.get("error") or ""
            if not error and "eresult" in payload:
                code = int(payload["eresult"])
                error = f"Steam rejected the item {payload.get('stage', 'update')} (EResult {code}: " \
                        f"{ERESULT_TEXT.get(code, 'see Steamworks EResult codes')})."
            raise RuntimeError(error.replace("NOT_LOGGED_ON: ", "") or "Steamworks helper reported a failure.")
        payload["ugc_version"] = ugc_version
        payload["dll_path"] = dll_path
        return payload

    def _update_tags_via_helper(self, dll_path, appid, publishedfileid, tags, change_note, timeout_seconds,
                                preview_path=None, init_app_id=None):
        payload = self._run_helper(dll_path, appid, publishedfileid, init_app_id=init_app_id, tags=tags,
                                   change_note=change_note, preview_path=preview_path,
                                   timeout_seconds=timeout_seconds)
        return {
            "publishedfileid": str(payload.get("publishedfileid") or publishedfileid),
            "needs_legal_agreement": bool(payload.get("needs_legal_agreement")),
            "method": "steamworks",
            "dll_path": dll_path,
            "ugc_version": payload.get("ugc_version"),
            "via": "32-bit helper",
        }

    def publish_item(self, appid, publishedfileid, *, title, description, content_folder, preview_path="",
                     tags=None, visibility=None, change_note="", init_app_id=None, base_dir=None,
                     timeout_seconds=4 * 3600, on_progress=None, on_created=None):
        """Create or update a Workshop item through the running Steam client (no SteamCMD).

        ``publishedfileid`` "0"/empty creates a new item. Blank description or
        preview on an update leave Steam's copy alone. Returns
        ``{"publishedfileid", "needs_legal_agreement", "created"}``.
        """
        if not steam_client_running():
            raise RuntimeError("Steam is not running or not signed in. Start Steam, then try again.")
        dll = self.helper_available(base_dir=base_dir)
        if not dll:
            raise FileNotFoundError("No Battlezone 98 Redux steam_api.dll (game or uploader tool) was found.")
        created = {}

        def remember(item_id, legal):
            created.update(id=item_id, legal=legal)
            if on_created:
                on_created(item_id, legal)

        is_new = str(publishedfileid or "0").strip() in ("", "0")
        try:
            payload = self._run_helper(
                dll, appid, "0" if is_new else publishedfileid, init_app_id=init_app_id,
                title=title, description=description, content=content_folder, preview_path=preview_path,
                tags=[t.strip() for t in (tags or []) if str(t).strip()], change_note=change_note,
                visibility=visibility, timeout_seconds=timeout_seconds, on_progress=on_progress,
                on_created=remember)
        except Exception as e:
            if created:
                # The item exists even though its upload failed: keep the id.
                e.created_item_id = created["id"]
            raise
        return {
            "publishedfileid": str(payload.get("publishedfileid") or created.get("id") or publishedfileid),
            "needs_legal_agreement": bool(payload.get("needs_legal_agreement") or created.get("legal")),
            "created": is_new,
        }

    def _configure_exports(self, dll):
        # SDK 1.58+ dropped SteamAPI_Init for SteamAPI_InitFlat /
        # SteamInternal_SteamAPI_Init, so each init entry point is optional.
        if hasattr(dll, "SteamAPI_InitFlat"):
            dll.SteamAPI_InitFlat.argtypes = [ctypes.c_char_p]
            dll.SteamAPI_InitFlat.restype = ctypes.c_int
        if hasattr(dll, "SteamAPI_Init"):
            dll.SteamAPI_Init.restype = ctypes.c_bool
        if hasattr(dll, "SteamInternal_SteamAPI_Init"):
            dll.SteamInternal_SteamAPI_Init.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            dll.SteamInternal_SteamAPI_Init.restype = ctypes.c_int
        for name in self.UGC_ACCESSORS + self.UTILS_ACCESSORS:
            if hasattr(dll, name):
                getattr(dll, name).restype = ctypes.c_void_p
        dll.SteamAPI_Shutdown.restype = None
        dll.SteamAPI_RunCallbacks.restype = None
        dll.SteamAPI_GetHSteamUser.restype = ctypes.c_int
        dll.SteamAPI_GetHSteamPipe.restype = ctypes.c_int
        dll.SteamClient.restype = ctypes.c_void_p

        dll.SteamAPI_ISteamClient_GetISteamUGC.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_char_p,
        ]
        dll.SteamAPI_ISteamClient_GetISteamUGC.restype = ctypes.c_void_p

        dll.SteamAPI_ISteamClient_GetISteamUtils.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_char_p,
        ]
        dll.SteamAPI_ISteamClient_GetISteamUtils.restype = ctypes.c_void_p

        dll.SteamAPI_ISteamUGC_StartItemUpdate.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint64,
        ]
        dll.SteamAPI_ISteamUGC_StartItemUpdate.restype = ctypes.c_uint64

        dll.SteamAPI_ISteamUGC_SetItemTags.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.POINTER(SteamParamStringArray),
        ]
        dll.SteamAPI_ISteamUGC_SetItemTags.restype = ctypes.c_bool

        dll.SteamAPI_ISteamUGC_SetItemPreview.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_char_p,
        ]
        dll.SteamAPI_ISteamUGC_SetItemPreview.restype = ctypes.c_bool

        dll.SteamAPI_ISteamUGC_SubmitItemUpdate.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_char_p,
        ]
        dll.SteamAPI_ISteamUGC_SubmitItemUpdate.restype = ctypes.c_uint64

        dll.SteamAPI_ISteamUtils_IsAPICallCompleted.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_bool),
        ]
        dll.SteamAPI_ISteamUtils_IsAPICallCompleted.restype = ctypes.c_bool

        dll.SteamAPI_ISteamUtils_GetAPICallResult.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_bool),
        ]
        dll.SteamAPI_ISteamUtils_GetAPICallResult.restype = ctypes.c_bool

    def _load_dll(self, dll_path):
        dll_dir = os.path.dirname(dll_path)
        add_dir = getattr(os, "add_dll_directory", None)
        if add_dir:
            dll_cookie = add_dir(dll_dir)
        else:
            dll_cookie = None
        try:
            # The flat API is cdecl; only 32-bit Python tells cdecl from stdcall.
            dll = ctypes.CDLL(dll_path)
        finally:
            if dll_cookie is not None:
                dll_cookie.close()
        self._configure_exports(dll)
        return dll

    def _init_steam_api(self, dll):
        """Start the Steam API with whichever entry point this DLL exports; raises on failure."""
        err = ctypes.create_string_buffer(1024)
        if hasattr(dll, "SteamAPI_InitFlat"):
            result = dll.SteamAPI_InitFlat(err)
            ok = result == 0
        elif hasattr(dll, "SteamAPI_Init"):
            ok = bool(dll.SteamAPI_Init())
        elif hasattr(dll, "SteamInternal_SteamAPI_Init"):
            ok = dll.SteamInternal_SteamAPI_Init(b"\0", err) == 0
        else:
            raise RuntimeError("This steam_api DLL exports no known SteamAPI init function.")
        if not ok:
            detail = err.value.decode("utf-8", "replace").strip()
            raise RuntimeError(
                "SteamAPI init failed"
                + (f": {detail}" if detail else "")
                + ". Make sure Steam is running and signed in to an account that owns Battlezone 98 Redux."
            )

    def _get_accessor_interface(self, dll, names):
        for name in names:
            if hasattr(dll, name):
                interface = getattr(dll, name)()
                if interface:
                    return interface, name
        return None, None

    def _get_ugc_interface(self, dll, client, h_user, h_pipe, dll_path=None):
        ugc, name = self._get_accessor_interface(dll, self.UGC_ACCESSORS)
        if ugc:
            return ugc, name
        built_for = embedded_interface_version(dll_path, "STEAMUGC_INTERFACE_VERSION") if dll_path else None
        if built_for:
            ugc = dll.SteamAPI_ISteamClient_GetISteamUGC(client, h_user, h_pipe, built_for.encode("ascii"))
            return (ugc, built_for) if ugc else (None, None)
        for version in self.STEAM_UGC_VERSIONS:
            ugc = dll.SteamAPI_ISteamClient_GetISteamUGC(client, h_user, h_pipe, version)
            if ugc:
                return ugc, version.decode("ascii")
        return None, None

    def _wait_for_submit_result(self, dll, steam_utils, api_call, timeout_seconds):
        deadline = time.time() + timeout_seconds
        call_failed = ctypes.c_bool(False)

        while time.time() < deadline:
            dll.SteamAPI_RunCallbacks()
            is_complete = dll.SteamAPI_ISteamUtils_IsAPICallCompleted(steam_utils, api_call, ctypes.byref(call_failed))
            if is_complete:
                if call_failed.value:
                    raise RuntimeError("Steamworks submit call failed before returning a result.")

                result = SubmitItemUpdateResult()
                io_failure = ctypes.c_bool(False)
                ok = dll.SteamAPI_ISteamUtils_GetAPICallResult(
                    steam_utils,
                    api_call,
                    ctypes.byref(result),
                    ctypes.sizeof(result),
                    self.SUBMIT_ITEM_UPDATE_CALLBACK_ID,
                    ctypes.byref(io_failure),
                )
                if not ok:
                    raise RuntimeError("Steamworks submit completed but no SubmitItemUpdateResult was returned.")
                if io_failure.value:
                    raise RuntimeError("Steamworks submit completed with I/O failure.")
                if result.result != self.ERESULT_OK:
                    raise RuntimeError(f"Steamworks submit returned EResult {result.result}.")
                return {
                    "publishedfileid": str(result.published_file_id),
                    "needs_legal_agreement": bool(result.needs_legal_agreement),
                }
            time.sleep(0.1)

        raise TimeoutError("Timed out waiting for Steamworks tag update to complete.")

    def try_update_tags(
        self,
        appid,
        publishedfileid,
        tags,
        change_note="",
        dll_path=None,
        base_dir=None,
        timeout_seconds=20.0,
        create_appid_file=False,
        init_app_id=None,
    ):
        clean_tags = [tag.strip() for tag in tags if str(tag).strip()]
        if not clean_tags:
            raise ValueError("No tags were provided.")
        return self.try_update_item(
            appid, publishedfileid, tags=clean_tags, change_note=change_note, dll_path=dll_path,
            base_dir=base_dir, timeout_seconds=timeout_seconds, create_appid_file=create_appid_file,
            init_app_id=init_app_id)

    def try_update_item(
        self,
        appid,
        publishedfileid,
        tags=None,
        preview_path=None,
        change_note="",
        dll_path=None,
        base_dir=None,
        timeout_seconds=20.0,
        create_appid_file=False,
        init_app_id=None,
    ):
        """Set an item's tags and/or preview image through Steamworks, as the signed-in Steam user.

        ``appid`` is the game the item belongs to (its consumer app).
        ``init_app_id`` is the app Steamworks runs as: pass the item's
        creator app. Steam silently ignores a preview change sent as any other
        app, and items made with the official Battlezone 98 Redux Uploader
        Tool were created by that tool (450970), not the game.
        """
        if os.name != "nt":
            raise RuntimeError("Steamworks item updates are only supported on Windows.")

        clean_tags = [tag.strip() for tag in (tags or []) if str(tag).strip()]
        if preview_path and not os.path.isfile(preview_path):
            raise FileNotFoundError(f"Preview image not found: {preview_path}")
        if not clean_tags and not preview_path:
            raise ValueError("Nothing to update: no tags and no preview image.")
        if not steam_client_running():
            raise RuntimeError("Steam is not running or not signed in. Start Steam, then try again.")

        # Prefer the helper: the game's own DLL, in a fresh process for every
        # update (a long-running app should not init/shut Steamworks down
        # over and over). A steam_api64.dll is only used in-process without it.
        game_dll = None if dll_path else self.helper_available(base_dir=base_dir)
        if game_dll:
            return self._update_tags_via_helper(
                game_dll, appid, publishedfileid, clean_tags, change_note, timeout_seconds,
                preview_path=preview_path, init_app_id=init_app_id)
        target_dll = dll_path or self.find_steam_api_path(base_dir=base_dir)
        if not target_dll:
            raise FileNotFoundError(
                f"Neither the game's steam_api.dll nor {STEAM_API_DLL} was found in known Battlezone locations."
            )

        created_appid_path = None
        if create_appid_file:
            created_appid_path = self._ensure_appid_file(base_dir, appid)
            if created_appid_path:
                self.log(f"Created temporary steam_appid.txt for native Steamworks tags: {created_appid_path}")

        self.log(f"Attempting Steamworks item update via {target_dll}")
        # Outside a Steam launch the API reads the AppID from SteamAppId (or a
        # steam_appid.txt in the working directory, which is rarely ours).
        saved_env = {key: os.environ.get(key) for key in ("SteamAppId", "SteamGameId")}
        os.environ["SteamAppId"] = str(init_app_id or appid)
        os.environ["SteamGameId"] = str(init_app_id or appid)
        dll = None
        try:
            dll = self._load_dll(target_dll)
            self._init_steam_api(dll)

            h_user = dll.SteamAPI_GetHSteamUser()
            h_pipe = dll.SteamAPI_GetHSteamPipe()
            client = dll.SteamClient()
            if not client or not h_user or not h_pipe:
                raise RuntimeError("Steamworks client handles were not available after SteamAPI_Init.")

            ugc, ugc_version = self._get_ugc_interface(dll, client, h_user, h_pipe, dll_path=target_dll)
            if not ugc:
                raise RuntimeError("Failed to acquire ISteamUGC interface.")

            steam_utils, _name = self._get_accessor_interface(dll, self.UTILS_ACCESSORS)
            if not steam_utils:
                utils_version = embedded_interface_version(target_dll, "SteamUtils", default="SteamUtils008")
                steam_utils = dll.SteamAPI_ISteamClient_GetISteamUtils(client, h_pipe, utils_version.encode("ascii"))
            if not steam_utils:
                raise RuntimeError("Failed to acquire ISteamUtils interface.")

            update_handle = dll.SteamAPI_ISteamUGC_StartItemUpdate(ugc, int(appid), int(publishedfileid))
            if not update_handle:
                raise RuntimeError("Steamworks StartItemUpdate returned an invalid handle.")

            if clean_tags:
                encoded_tags = [tag.encode("utf-8") for tag in clean_tags]
                tag_array = (ctypes.c_char_p * len(encoded_tags))(*encoded_tags)
                steam_tags = SteamParamStringArray(strings=tag_array, num_strings=len(encoded_tags))
                if not dll.SteamAPI_ISteamUGC_SetItemTags(ugc, update_handle, ctypes.byref(steam_tags)):
                    raise RuntimeError("Steamworks SetItemTags returned failure.")

            if preview_path:
                if not dll.SteamAPI_ISteamUGC_SetItemPreview(
                        ugc, update_handle, os.path.abspath(preview_path).encode("utf-8")):
                    raise RuntimeError("Steamworks SetItemPreview returned failure.")

            submit_call = dll.SteamAPI_ISteamUGC_SubmitItemUpdate(
                ugc,
                update_handle,
                (change_note or "").encode("utf-8"),
            )
            if not submit_call:
                raise RuntimeError("Steamworks SubmitItemUpdate returned an invalid API call handle.")

            result = self._wait_for_submit_result(dll, steam_utils, submit_call, timeout_seconds=timeout_seconds)
            result["method"] = "steamworks"
            result["ugc_version"] = ugc_version
            result["dll_path"] = target_dll
            return result
        finally:
            if dll is not None:
                try:
                    dll.SteamAPI_Shutdown()
                except Exception:
                    pass
            for key, value in saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            if created_appid_path and os.path.exists(created_appid_path):
                try:
                    os.remove(created_appid_path)
                    self.log("Removed temporary steam_appid.txt after native Steamworks tag attempt.")
                except Exception:
                    pass
