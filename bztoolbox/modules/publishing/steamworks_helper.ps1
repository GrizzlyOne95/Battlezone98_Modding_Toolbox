# Publishes or updates a Workshop item through the 32-bit steam_api.dll that
# ships with Battlezone 98 Redux (or the official uploader tool), using the
# running Steam client's login: no SteamCMD, password or Steam Guard. The
# toolbox runs 64-bit and cannot load that DLL itself, so it runs this script
# under the 32-bit Windows PowerShell (SysWOW64).
#
# Output, one JSON object per line:
#   {"progress": {"status": 3, "processed": 1234, "total": 5678}}   while uploading
#   {"created": "<id>", "needs_legal_agreement": false}               after creating a new item
#   {"ok": true, ...} or {"ok": false, "error": ...}                  last line
#
# Only the fields that are passed are changed: a blank description or preview
# on an update keeps what is on Steam.
param(
    [Parameter(Mandatory = $true)][string]$DllPath,
    # The game the item belongs to (its consumer app).
    [Parameter(Mandatory = $true)][uint32]$AppId,
    # The app Steamworks runs as. Steam applies changes such as the preview only
    # from the app that created the item (the official uploader tool is its own app).
    [uint32]$InitAppId = 0,
    # 0 creates a new item.
    [uint64]$ItemId = 0,
    [string]$TitleB64 = "",
    [string]$DescriptionB64 = "",
    [string]$ContentB64 = "",
    [string]$PreviewB64 = "",
    [string]$TagsB64 = "",
    [string]$NoteB64 = "",
    # -1 leaves it unchanged; 0 public, 1 friends, 2 private, 3 unlisted.
    [int]$Visibility = -1,
    [string]$UgcVersion = "STEAMUGC_INTERFACE_VERSION009",
    [string]$UtilsVersion = "SteamUtils008",
    [string]$UserVersion = "SteamUser019",
    [int]$TimeoutSeconds = 20
)

$ErrorActionPreference = "Stop"

function Write-Json($value) {
    [Console]::Out.WriteLine(($value | ConvertTo-Json -Compress))
}

function Decode($b64) {
    if (-not $b64) { return "" }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64))
}

if ([IntPtr]::Size -ne 4) {
    Write-Json @{ ok = $false; error = "The Steamworks helper must run in 32-bit PowerShell." }
    exit 2
}

$source = @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public static class BzSteamworks
{
    [DllImport("kernel32", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr LoadLibraryW(string path);

    [DllImport("kernel32", CharSet = CharSet.Ansi, ExactSpelling = true)]
    static extern IntPtr GetProcAddress(IntPtr module, string name);

    [StructLayout(LayoutKind.Sequential)]
    struct ParamStringArray { public IntPtr Strings; public int Count; }

    // Steam call results are 8-byte packed on Windows. Older SDKs end
    // SubmitItemUpdateResult_t after the legal-agreement flag (8 bytes); newer
    // ones add the item id.
    [StructLayout(LayoutKind.Explicit, Size = 16)]
    struct SubmitResult
    {
        [FieldOffset(0)] public int Result;
        [FieldOffset(4)] public byte NeedsLegalAgreement;
        [FieldOffset(8)] public ulong PublishedFileId;
    }

    [StructLayout(LayoutKind.Explicit, Size = 24)]
    struct CreateResult
    {
        [FieldOffset(0)] public int Result;
        [FieldOffset(8)] public ulong PublishedFileId;
        [FieldOffset(16)] public byte NeedsLegalAgreement;
    }

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)] delegate bool BoolFn();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate void VoidFn();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int IntFn();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate IntPtr PtrFn();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate IntPtr GetUgcFn(IntPtr client, int user, int pipe, [MarshalAs(UnmanagedType.LPStr)] string version);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate IntPtr GetUtilsFn(IntPtr client, int pipe, [MarshalAs(UnmanagedType.LPStr)] string version);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)] delegate bool LoggedOnFn(IntPtr user);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate ulong CreateItemFn(IntPtr ugc, uint appId, int fileType);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate ulong StartUpdateFn(IntPtr ugc, uint appId, ulong itemId);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)] delegate bool SetStringFn(IntPtr ugc, ulong handle, IntPtr value);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)] delegate bool SetIntFn(IntPtr ugc, ulong handle, int value);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)] delegate bool SetTagsFn(IntPtr ugc, ulong handle, ref ParamStringArray tags);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate ulong SubmitFn(IntPtr ugc, ulong handle, IntPtr note);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate int ProgressFn(IntPtr ugc, ulong handle, out ulong processed, out ulong total);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)] delegate bool IsDoneFn(IntPtr utils, ulong call, [MarshalAs(UnmanagedType.I1)] out bool failed);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)] delegate bool GetSubmitResultFn(IntPtr utils, ulong call, ref SubmitResult result, int size, int expected, [MarshalAs(UnmanagedType.I1)] out bool failed);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)] delegate bool GetCreateResultFn(IntPtr utils, ulong call, ref CreateResult result, int size, int expected, [MarshalAs(UnmanagedType.I1)] out bool failed);

    const int CreateItemCallback = 3403;
    const int SubmitItemUpdateCallback = 3404;
    const int FileTypeCommunity = 0;

    static IntPtr module;

    static T Fn<T>(string name) where T : class
    {
        IntPtr proc = GetProcAddress(module, name);
        if (proc == IntPtr.Zero) throw new Exception("steam_api.dll does not export " + name);
        return Marshal.GetDelegateForFunctionPointer(proc, typeof(T)) as T;
    }

    static IntPtr Utf8(string value, List<IntPtr> owned)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(value ?? "");
        IntPtr ptr = Marshal.AllocHGlobal(bytes.Length + 1);
        Marshal.Copy(bytes, 0, ptr, bytes.Length);
        Marshal.WriteByte(ptr, bytes.Length, 0);
        owned.Add(ptr);
        return ptr;
    }

    static string Json(string text)
    {
        StringBuilder sb = new StringBuilder("\"");
        foreach (char c in text ?? "")
        {
            if (c == '"' || c == '\\') sb.Append('\\').Append(c);
            else if (c < ' ') sb.Append("\\u").Append(((int)c).ToString("x4"));
            else sb.Append(c);
        }
        return sb.Append('"').ToString();
    }

    static void Emit(string json)
    {
        Console.Out.WriteLine(json);
        Console.Out.Flush();
    }

    // Waits for an API call, running callbacks; reports upload progress for an update handle.
    static void Wait(IntPtr utils, ulong call, ulong progressHandle, IntPtr ugc, int timeoutSeconds, string what)
    {
        VoidFn runCallbacks = Fn<VoidFn>("SteamAPI_RunCallbacks");
        IsDoneFn isDone = Fn<IsDoneFn>("SteamAPI_ISteamUtils_IsAPICallCompleted");
        ProgressFn progress = progressHandle != 0 ? Fn<ProgressFn>("SteamAPI_ISteamUGC_GetItemUpdateProgress") : null;
        DateTime deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        DateTime nextReport = DateTime.UtcNow;
        string last = "";
        while (DateTime.UtcNow < deadline)
        {
            runCallbacks();
            bool failed;
            if (isDone(utils, call, out failed))
            {
                if (failed) throw new Exception("Steam lost the " + what + " call before it finished.");
                return;
            }
            if (progress != null && DateTime.UtcNow >= nextReport)
            {
                ulong done, total;
                int status = progress(ugc, progressHandle, out done, out total);
                string line = "{\"progress\": {\"status\": " + status + ", \"processed\": " + done + ", \"total\": " + total + "}}";
                if (line != last) { Emit(line); last = line; }
                nextReport = DateTime.UtcNow.AddSeconds(1);
            }
            Thread.Sleep(100);
        }
        throw new Exception("Timed out waiting for Steam to finish the " + what + ".");
    }

    public static string Run(string dllPath, uint appId, ulong itemId, string title, string description,
                             string content, string preview, string[] tags, string note, int visibility,
                             string ugcVersion, string utilsVersion, string userVersion, int timeoutSeconds)
    {
        module = LoadLibraryW(dllPath);
        if (module == IntPtr.Zero)
            throw new Exception("Could not load " + dllPath + " (Win32 error " + Marshal.GetLastWin32Error() + ")");

        if (!Fn<BoolFn>("SteamAPI_Init")())
            throw new Exception("SteamAPI_Init failed. Make sure Steam is running and signed in to an account that owns Battlezone 98 Redux.");

        List<IntPtr> owned = new List<IntPtr>();
        try
        {
            IntPtr client = Fn<PtrFn>("SteamClient")();
            int user = Fn<IntFn>("SteamAPI_GetHSteamUser")();
            int pipe = Fn<IntFn>("SteamAPI_GetHSteamPipe")();
            if (client == IntPtr.Zero || user == 0 || pipe == 0)
                throw new Exception("Steam client handles were not available after SteamAPI_Init.");

            IntPtr steamUser = Fn<GetUgcFn>("SteamAPI_ISteamClient_GetISteamUser")(client, user, pipe, userVersion);
            if (steamUser != IntPtr.Zero && !Fn<LoggedOnFn>("SteamAPI_ISteamUser_BLoggedOn")(steamUser))
                throw new Exception("NOT_LOGGED_ON: The Steam client is running but not connected to Steam. "
                    + "If SteamCMD just logged in with this account it signed the client out (\"Session Replaced\"); "
                    + "reconnect Steam, then try again.");

            IntPtr ugc = Fn<GetUgcFn>("SteamAPI_ISteamClient_GetISteamUGC")(client, user, pipe, ugcVersion);
            if (ugc == IntPtr.Zero) throw new Exception("Steam did not provide " + ugcVersion + ".");
            IntPtr utils = Fn<GetUtilsFn>("SteamAPI_ISteamClient_GetISteamUtils")(client, pipe, utilsVersion);
            if (utils == IntPtr.Zero) throw new Exception("Steam did not provide " + utilsVersion + ".");

            bool needsLegal = false;
            if (itemId == 0)
            {
                ulong createCall = Fn<CreateItemFn>("SteamAPI_ISteamUGC_CreateItem")(ugc, appId, FileTypeCommunity);
                if (createCall == 0) throw new Exception("CreateItem returned an invalid call handle.");
                Wait(utils, createCall, 0, ugc, 60, "item creation");
                CreateResult created = new CreateResult();
                bool createIo;
                if (!Fn<GetCreateResultFn>("SteamAPI_ISteamUtils_GetAPICallResult")(utils, createCall, ref created, 24, CreateItemCallback, out createIo))
                    throw new Exception("Steam returned no CreateItemResult.");
                if (created.Result != 1) return "{\"ok\": false, \"eresult\": " + created.Result + ", \"stage\": \"create\"}";
                itemId = created.PublishedFileId;
                needsLegal = created.NeedsLegalAgreement != 0;
                // Reported at once so the toolbox links the new id even if the upload below fails.
                Emit("{\"created\": \"" + itemId + "\", \"needs_legal_agreement\": " + (needsLegal ? "true" : "false") + "}");
            }

            ulong handle = Fn<StartUpdateFn>("SteamAPI_ISteamUGC_StartItemUpdate")(ugc, appId, itemId);
            if (handle == 0) throw new Exception("StartItemUpdate returned an invalid handle.");

            SetStringFn setString;
            if (!String.IsNullOrEmpty(title))
            {
                setString = Fn<SetStringFn>("SteamAPI_ISteamUGC_SetItemTitle");
                if (!setString(ugc, handle, Utf8(title, owned))) throw new Exception("SetItemTitle returned failure.");
            }
            if (!String.IsNullOrEmpty(description))
            {
                setString = Fn<SetStringFn>("SteamAPI_ISteamUGC_SetItemDescription");
                if (!setString(ugc, handle, Utf8(description, owned))) throw new Exception("SetItemDescription returned failure.");
            }
            if (visibility >= 0)
            {
                if (!Fn<SetIntFn>("SteamAPI_ISteamUGC_SetItemVisibility")(ugc, handle, visibility))
                    throw new Exception("SetItemVisibility returned failure.");
            }
            if (tags.Length > 0)
            {
                IntPtr array = Marshal.AllocHGlobal(IntPtr.Size * tags.Length);
                owned.Add(array);
                for (int i = 0; i < tags.Length; i++)
                    Marshal.WriteIntPtr(array, i * IntPtr.Size, Utf8(tags[i], owned));
                ParamStringArray tagArray = new ParamStringArray { Strings = array, Count = tags.Length };
                if (!Fn<SetTagsFn>("SteamAPI_ISteamUGC_SetItemTags")(ugc, handle, ref tagArray))
                    throw new Exception("SetItemTags returned failure.");
            }
            if (!String.IsNullOrEmpty(content))
            {
                setString = Fn<SetStringFn>("SteamAPI_ISteamUGC_SetItemContent");
                if (!setString(ugc, handle, Utf8(content, owned))) throw new Exception("SetItemContent returned failure.");
            }
            if (!String.IsNullOrEmpty(preview))
            {
                setString = Fn<SetStringFn>("SteamAPI_ISteamUGC_SetItemPreview");
                if (!setString(ugc, handle, Utf8(preview, owned))) throw new Exception("SetItemPreview returned failure.");
            }

            ulong call = Fn<SubmitFn>("SteamAPI_ISteamUGC_SubmitItemUpdate")(ugc, handle, Utf8(note, owned));
            if (call == 0) throw new Exception("SubmitItemUpdate returned an invalid call handle.");
            Wait(utils, call, handle, ugc, timeoutSeconds, "upload");

            SubmitResult result = new SubmitResult();
            bool ioFailure;
            GetSubmitResultFn getResult = Fn<GetSubmitResultFn>("SteamAPI_ISteamUtils_GetAPICallResult");
            // The Steam client sizes the result by its own SDK; try the current
            // layout, then the shorter pre-1.40 one.
            bool ok = getResult(utils, call, ref result, 16, SubmitItemUpdateCallback, out ioFailure)
                      || getResult(utils, call, ref result, 8, SubmitItemUpdateCallback, out ioFailure);
            if (!ok) throw new Exception("Steam returned no SubmitItemUpdateResult.");
            if (ioFailure) throw new Exception("Steam reported an I/O failure for the item update.");
            needsLegal = needsLegal || result.NeedsLegalAgreement != 0;
            return "{\"ok\": " + (result.Result == 1 ? "true" : "false")
                   + ", \"eresult\": " + result.Result
                   + ", \"stage\": \"submit\""
                   + ", \"needs_legal_agreement\": " + (needsLegal ? "true" : "false")
                   + ", \"publishedfileid\": " + Json(itemId.ToString()) + "}";
        }
        finally
        {
            foreach (IntPtr ptr in owned) Marshal.FreeHGlobal(ptr);
            try { Fn<VoidFn>("SteamAPI_Shutdown")(); } catch { }
        }
    }
}
"@

try {
    if ($InitAppId -eq 0) { $InitAppId = $AppId }
    $env:SteamAppId = [string]$InitAppId
    $env:SteamGameId = [string]$InitAppId
    # One tag per line. (Not JSON: Windows PowerShell 5 hands a JSON array
    # back as one object, which [string[]] would join into a single tag.)
    [string[]]$tags = @()
    $tagText = Decode $TagsB64
    if ($tagText) { $tags = @($tagText -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
    $title = Decode $TitleB64
    $description = Decode $DescriptionB64
    $content = Decode $ContentB64
    $preview = Decode $PreviewB64
    $note = Decode $NoteB64
    if ($ItemId -eq 0 -and (-not $title -or -not $content)) { throw "A new item needs a title and a content folder." }
    if ($ItemId -ne 0 -and -not ($title -or $description -or $content -or $preview -or $tags.Count -or $Visibility -ge 0)) {
        throw "Nothing to update."
    }
    Add-Type -TypeDefinition $source -Language CSharp
    $json = [BzSteamworks]::Run($DllPath, $AppId, $ItemId, $title, $description, $content, $preview, $tags, $note,
                                $Visibility, $UgcVersion, $UtilsVersion, $UserVersion, $TimeoutSeconds)
    [Console]::Out.WriteLine($json)
    if ($json -like '*"ok": true*') { exit 0 } else { exit 1 }
}
catch {
    $message = $_.Exception.Message
    if ($_.Exception.InnerException) { $message = $_.Exception.InnerException.Message }
    Write-Json @{ ok = $false; error = $message }
    exit 1
}
