# Sets a Workshop item's tags and/or preview image through the 32-bit steam_api.dll that ships
# with Battlezone 98 Redux. The toolbox runs 64-bit and cannot load that DLL
# itself, so it runs this script under the 32-bit Windows PowerShell
# (SysWOW64). Prints one JSON line: {"ok": true, ...} or {"ok": false, "error": ...}.
param(
    [Parameter(Mandatory = $true)][string]$DllPath,
    [Parameter(Mandatory = $true)][uint32]$AppId,
    # The app Steamworks runs as. Steam applies preview changes only from the
    # app that created the item (the official uploader tool is its own app).
    [uint32]$InitAppId = 0,
    [Parameter(Mandatory = $true)][uint64]$ItemId,
    [string]$TagsB64 = "",
    [string]$NoteB64 = "",
    [string]$PreviewB64 = "",
    [string]$UgcVersion = "STEAMUGC_INTERFACE_VERSION009",
    [string]$UtilsVersion = "SteamUtils008",
    [int]$TimeoutSeconds = 20
)

$ErrorActionPreference = "Stop"

function Write-Result($value) {
    [Console]::Out.WriteLine(($value | ConvertTo-Json -Compress))
}

if ([IntPtr]::Size -ne 4) {
    Write-Result @{ ok = $false; error = "The tag helper must run in 32-bit PowerShell." }
    exit 2
}

$source = @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public static class BzSteamTags
{
    [DllImport("kernel32", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr LoadLibraryW(string path);

    [DllImport("kernel32", CharSet = CharSet.Ansi, ExactSpelling = true)]
    static extern IntPtr GetProcAddress(IntPtr module, string name);

    [StructLayout(LayoutKind.Sequential)]
    struct ParamStringArray { public IntPtr Strings; public int Count; }

    // SubmitItemUpdateResult_t, 8-byte packed on Windows. Older SDKs end
    // after the legal-agreement flag (8 bytes), newer ones add the item id.
    [StructLayout(LayoutKind.Explicit, Size = 16)]
    struct SubmitResult
    {
        [FieldOffset(0)] public int Result;
        [FieldOffset(4)] public byte NeedsLegalAgreement;
        [FieldOffset(8)] public ulong PublishedFileId;
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
    delegate ulong StartUpdateFn(IntPtr ugc, uint appId, ulong itemId);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)] delegate bool SetTagsFn(IntPtr ugc, ulong handle, ref ParamStringArray tags);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)] delegate bool SetPreviewFn(IntPtr ugc, ulong handle, IntPtr path);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate ulong SubmitFn(IntPtr ugc, ulong handle, IntPtr note);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)] delegate bool IsDoneFn(IntPtr utils, ulong call, [MarshalAs(UnmanagedType.I1)] out bool failed);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)] delegate bool GetResultFn(IntPtr utils, ulong call, ref SubmitResult result, int size, int expected, [MarshalAs(UnmanagedType.I1)] out bool failed);

    const int SubmitItemUpdateCallback = 3404;

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

    public static string[] Update(string dllPath, uint appId, ulong itemId, string[] tags, string previewPath,
                                  string note, string ugcVersion, string utilsVersion, int timeoutSeconds)
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

            IntPtr ugc = Fn<GetUgcFn>("SteamAPI_ISteamClient_GetISteamUGC")(client, user, pipe, ugcVersion);
            if (ugc == IntPtr.Zero) throw new Exception("Steam did not provide " + ugcVersion + ".");
            IntPtr utils = Fn<GetUtilsFn>("SteamAPI_ISteamClient_GetISteamUtils")(client, pipe, utilsVersion);
            if (utils == IntPtr.Zero) throw new Exception("Steam did not provide " + utilsVersion + ".");

            ulong handle = Fn<StartUpdateFn>("SteamAPI_ISteamUGC_StartItemUpdate")(ugc, appId, itemId);
            if (handle == 0) throw new Exception("StartItemUpdate returned an invalid handle.");

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
            if (!String.IsNullOrEmpty(previewPath))
            {
                if (!Fn<SetPreviewFn>("SteamAPI_ISteamUGC_SetItemPreview")(ugc, handle, Utf8(previewPath, owned)))
                    throw new Exception("SetItemPreview returned failure.");
            }

            ulong call = Fn<SubmitFn>("SteamAPI_ISteamUGC_SubmitItemUpdate")(ugc, handle, Utf8(note, owned));
            if (call == 0) throw new Exception("SubmitItemUpdate returned an invalid call handle.");

            VoidFn runCallbacks = Fn<VoidFn>("SteamAPI_RunCallbacks");
            IsDoneFn isDone = Fn<IsDoneFn>("SteamAPI_ISteamUtils_IsAPICallCompleted");
            GetResultFn getResult = Fn<GetResultFn>("SteamAPI_ISteamUtils_GetAPICallResult");
            DateTime deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
            while (DateTime.UtcNow < deadline)
            {
                runCallbacks();
                bool failed;
                if (isDone(utils, call, out failed))
                {
                    if (failed) throw new Exception("The Steam submit call failed before returning a result.");
                    SubmitResult result = new SubmitResult();
                    bool ioFailure;
                    // The Steam client sizes the result by its own SDK; try the
                    // current layout, then the shorter pre-1.40 one.
                    bool ok = getResult(utils, call, ref result, 16, SubmitItemUpdateCallback, out ioFailure)
                              || getResult(utils, call, ref result, 8, SubmitItemUpdateCallback, out ioFailure);
                    if (!ok) throw new Exception("Steam returned no SubmitItemUpdateResult.");
                    if (ioFailure) throw new Exception("Steam reported an I/O failure for the tag update.");
                    return new string[] {
                        result.Result.ToString(),
                        result.NeedsLegalAgreement != 0 ? "1" : "0",
                        result.PublishedFileId.ToString()
                    };
                }
                Thread.Sleep(100);
            }
            throw new Exception("Timed out waiting for Steam to confirm the tag update.");
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
    if ($TagsB64) {
        $tagText = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($TagsB64))
        $tags = @($tagText -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }
    $preview = ""
    if ($PreviewB64) { $preview = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($PreviewB64)) }
    if ($tags.Count -eq 0 -and -not $preview) { throw "Nothing to update: no tags and no preview image." }
    $note = ""
    if ($NoteB64) { $note = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($NoteB64)) }
    Add-Type -TypeDefinition $source -Language CSharp
    $r = [BzSteamTags]::Update($DllPath, $AppId, $ItemId, $tags, $preview, $note, $UgcVersion, $UtilsVersion, $TimeoutSeconds)
    $eresult = [int]$r[0]
    if ($eresult -ne 1) {
        Write-Result @{ ok = $false; error = "Steam rejected the item update (EResult $eresult)."; eresult = $eresult }
        exit 1
    }
    Write-Result @{ ok = $true; eresult = $eresult; needs_legal_agreement = ($r[1] -eq "1"); publishedfileid = $r[2] }
    exit 0
}
catch {
    $message = $_.Exception.Message
    if ($_.Exception.InnerException) { $message = $_.Exception.InnerException.Message }
    Write-Result @{ ok = $false; error = $message }
    exit 1
}
