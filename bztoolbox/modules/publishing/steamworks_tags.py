import ctypes
import os
import struct
import time

# The DLL has to match this process: 64-bit Python can only load
# steam_api64.dll, and Battlezone 98 Redux ships just the 32-bit steam_api.dll.
IS_64BIT = struct.calcsize("P") == 8
STEAM_API_DLL = "steam_api64.dll" if IS_64BIT else "steam_api.dll"


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

    def _wrong_architecture_dll(self, base_dir=None):
        """A steam_api.dll this 64-bit process cannot load, to explain the failure."""
        if not IS_64BIT:
            return None
        for directory in self._candidate_dirs(base_dir):
            path = os.path.join(directory, "steam_api.dll")
            if os.path.exists(path):
                return os.path.normpath(path)
        return None

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
            dll = ctypes.WinDLL(dll_path)
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

    def _get_ugc_interface(self, dll, client, h_user, h_pipe):
        ugc, name = self._get_accessor_interface(dll, self.UGC_ACCESSORS)
        if ugc:
            return ugc, name
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
    ):
        if os.name != "nt":
            raise RuntimeError("Steamworks tag update is only supported on Windows.")

        clean_tags = [tag.strip() for tag in tags if str(tag).strip()]
        if not clean_tags:
            raise ValueError("No tags were provided.")

        target_dll = dll_path or self.find_steam_api_path(base_dir=base_dir)
        if not target_dll:
            wrong = self._wrong_architecture_dll(base_dir=base_dir)
            if wrong:
                raise FileNotFoundError(
                    f"Only the 32-bit {wrong} was found; the toolbox runs 64-bit and needs {STEAM_API_DLL}. "
                    f"Put {STEAM_API_DLL} (Steamworks SDK redistributable) in {base_dir or 'the game folder'}."
                )
            raise FileNotFoundError(f"{STEAM_API_DLL} was not found in known Battlezone locations.")

        created_appid_path = None
        if create_appid_file:
            created_appid_path = self._ensure_appid_file(base_dir, appid)
            if created_appid_path:
                self.log(f"Created temporary steam_appid.txt for native Steamworks tags: {created_appid_path}")

        self.log(f"Attempting Steamworks tag update via {target_dll}")
        # Outside a Steam launch the API reads the AppID from SteamAppId (or a
        # steam_appid.txt in the working directory, which is rarely ours).
        saved_env = {key: os.environ.get(key) for key in ("SteamAppId", "SteamGameId")}
        os.environ["SteamAppId"] = str(appid)
        os.environ["SteamGameId"] = str(appid)
        dll = None
        try:
            dll = self._load_dll(target_dll)
            self._init_steam_api(dll)

            h_user = dll.SteamAPI_GetHSteamUser()
            h_pipe = dll.SteamAPI_GetHSteamPipe()
            client = dll.SteamClient()
            if not client or not h_user or not h_pipe:
                raise RuntimeError("Steamworks client handles were not available after SteamAPI_Init.")

            ugc, ugc_version = self._get_ugc_interface(dll, client, h_user, h_pipe)
            if not ugc:
                raise RuntimeError("Failed to acquire ISteamUGC interface.")

            steam_utils, _name = self._get_accessor_interface(dll, self.UTILS_ACCESSORS)
            if not steam_utils:
                steam_utils = dll.SteamAPI_ISteamClient_GetISteamUtils(client, h_pipe, self.STEAM_UTILS_VERSION)
            if not steam_utils:
                raise RuntimeError("Failed to acquire ISteamUtils interface.")

            update_handle = dll.SteamAPI_ISteamUGC_StartItemUpdate(ugc, int(appid), int(publishedfileid))
            if not update_handle:
                raise RuntimeError("Steamworks StartItemUpdate returned an invalid handle.")

            encoded_tags = [tag.encode("utf-8") for tag in clean_tags]
            tag_array = (ctypes.c_char_p * len(encoded_tags))(*encoded_tags)
            steam_tags = SteamParamStringArray(strings=tag_array, num_strings=len(encoded_tags))

            if not dll.SteamAPI_ISteamUGC_SetItemTags(ugc, update_handle, ctypes.byref(steam_tags)):
                raise RuntimeError("Steamworks SetItemTags returned failure.")

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
