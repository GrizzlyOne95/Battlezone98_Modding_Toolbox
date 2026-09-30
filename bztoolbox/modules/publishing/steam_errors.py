"""Every error Steam can hand back to a Workshop upload, in words.

Steam reports failures in four shapes, all covered here:

* **EResult** numbers (``steamclientpublic.h``), returned by Steamworks
  CreateItem / SubmitItemUpdate, printed by SteamCMD as their spaced name,
  e.g. ``ERROR! Failed to update workshop item (Access Denied).``, and sent
  by the Steam Web API in its ``x-eresult`` response header.
* **ESteamAPIInitResult**, from ``SteamAPI_InitFlat``.
* **SteamCMD** console and log messages that carry no EResult.
* **HTTP** statuses from the Steam Web API.

``explain_eresult`` / ``describe_eresult`` turn a code into a message a
modder can act on; ``diagnose_steamcmd_output`` scans SteamCMD output or logs.
"""

import re
from collections import namedtuple

SteamError = namedtuple("SteamError", "code name meaning fix")

WORKSHOP_LEGAL_URL = "https://steamcommunity.com/sharedfiles/workshoplegalagreement"
STEAM_STATUS_URL = "https://steamstat.us"

# Every EResult Steam defines. ``meaning`` is what went wrong for a Workshop
# upload; ``fix`` is what the modder can do about it ("" when nothing can).
_ERESULTS = [
    (0, "None", "Steam returned no result at all.",
     "Retry; if it repeats, restart Steam."),
    (1, "OK", "Success.", ""),
    (2, "Fail", "Steam reported a generic failure without saying why. For Workshop uploads this usually means "
     "the Workshop servers had a problem, the content folder could not be read, or a SteamCMD manifest "
     "upload timed out.",
     "Wait a few minutes and retry. Check that no file in the content folder is open in another program, "
     "and check " + STEAM_STATUS_URL + " for a Steam outage."),
    (3, "NoConnection", "There is no connection to Steam (the client is offline or cannot reach the servers).",
     "Check your internet connection, make sure Steam is online (not in Offline Mode), then retry."),
    (5, "InvalidPassword", "The password is wrong, or the saved login is no longer valid.",
     "Re-enter the password. If SteamCMD used a cached login, sign in again to refresh it."),
    (6, "LoggedInElsewhere", "The same account is signed in somewhere else and that session blocks this one.",
     "Close Steam or SteamCMD on the other machine or window, then retry."),
    (7, "InvalidProtocolVer", "This Steam client or SteamCMD is too old for the Steam servers.",
     "Let Steam / SteamCMD update itself (restart it), then retry."),
    (8, "InvalidParam", "Steam rejected one of the values sent: usually the title (over 128 characters), the "
     "description (over 8000 characters), a tag, the visibility, the change note, or an empty/invalid "
     "content or preview path.",
     "Shorten the title and description, remove unusual characters from tags, and check the content folder "
     "and preview image paths."),
    (9, "FileNotFound", "Steam could not find something it needed: the content folder, the preview image, or "
     "the Workshop item itself (deleted, or the wrong Workshop ID).",
     "Check the content folder and preview paths exist, and that the linked Workshop ID is still yours on "
     "Steam. Unlink the item to publish it as a new one."),
    (10, "Busy", "Steam is busy with another request right now.",
     "Wait a moment and retry."),
    (11, "InvalidState", "The item or account is not in a state that allows this change (for example an "
     "update is already being processed for it).",
     "Wait for any other upload of this item to finish, then retry."),
    (12, "InvalidName", "A name was rejected (title or file name contains characters Steam does not accept).",
     "Remove unusual characters from the title and from file names in the content folder."),
    (13, "InvalidEmail", "The account's e-mail address is invalid.",
     "Fix the account e-mail in Steam account settings."),
    (14, "DuplicateName", "A name is already in use (often the preview file name matches an existing one).",
     "Rename the preview image or retry; the toolbox renames previews by content to avoid this."),
    (15, "AccessDenied", "Steam refused access. For Workshop uploads this means one of: the item belongs to "
     "another Steam account; the account does not own Battlezone 98 Redux; the preview image could not be "
     "read; or the Workshop legal agreement has not been accepted.",
     "Sign in with the account that owns both the game and this Workshop item, check the preview image is a "
     "valid JPG/PNG/GIF, and accept the agreement at " + WORKSHOP_LEGAL_URL + "."),
    (16, "Timeout", "The operation took too long and Steam gave up.",
     "Retry. Large uploads on slow connections can take a long time; avoid sleeping the PC mid-upload."),
    (17, "Banned", "The account is banned: VAC, game, community or Workshop ban for this game.",
     "Nothing the toolbox can fix; check the account's standing at help.steampowered.com."),
    (18, "AccountNotFound", "The Steam account does not exist.",
     "Check the user name."),
    (19, "InvalidSteamID", "The Steam ID sent is not valid.",
     "Check the Workshop owner / SteamID64 setting."),
    (20, "ServiceUnavailable", "The Steam or Workshop service is down or overloaded.",
     "Wait and retry later; check " + STEAM_STATUS_URL + "."),
    (21, "NotLoggedOn", "Steam is not signed in.",
     "Sign in to Steam (or SteamCMD), then retry."),
    (22, "Pending", "The request is still being processed by Steam.",
     "Wait a moment; if the item does not update, retry."),
    (23, "EncryptionFailure", "Encryption or decryption failed while talking to Steam.",
     "Retry; check the system clock is correct and nothing (proxy/antivirus) is intercepting Steam traffic."),
    (24, "InsufficientPrivilege", "The account is not allowed to upload right now: a Workshop/community "
     "restriction, a locked account, or a limited (unpurchased) account.",
     "Limited accounts must spend at least $5 on Steam before they can publish. Otherwise check the "
     "account's restrictions at help.steampowered.com."),
    (25, "LimitExceeded", "A size or count limit was hit: most often the preview image is over 1 MB, or the "
     "account ran out of Steam Cloud/Workshop quota.",
     "Make the preview image smaller than 1 MB (the toolbox can resize it), and delete unused Workshop items "
     "if you have many."),
    (26, "Revoked", "Access (a license, key or session) was revoked.",
     "Sign in again; check the account still owns the game."),
    (27, "Expired", "A license, key or login session has expired.",
     "Sign in again, then retry."),
    (28, "AlreadyRedeemed", "The key was already redeemed.", ""),
    (29, "DuplicateRequest", "The same request was already sent and is still in progress.",
     "Wait for the first upload to finish; do not publish the same item twice at once."),
    (30, "AlreadyOwned", "The account already owns this.", ""),
    (31, "IPNotFound", "The IP address was not found.", "Check your network connection."),
    (32, "PersistFailed", "Steam failed to save the change on its servers.",
     "Retry later."),
    (33, "LockingFailed", "Steam could not lock the Workshop item for editing (another update holds it).",
     "Wait for other uploads of this item (including from another PC or SteamCMD) to finish, then retry."),
    (34, "LogonSessionReplaced", "The login session was replaced: the same account signed in elsewhere. "
     "SteamCMD signing in signs the Steam client out, and vice versa.",
     "Reconnect Steam (or re-run SteamCMD) and retry; avoid running both with the same account at once."),
    (35, "ConnectFailed", "Could not connect to Steam.",
     "Check your internet connection and firewall, then retry."),
    (36, "HandshakeFailed", "The secure connection to Steam could not be set up.",
     "Retry; check the system clock and any proxy or antivirus intercepting traffic."),
    (37, "IOFailure", "A read/write or network I/O error happened during the upload.",
     "Check the content folder is readable and not on a disconnected drive, that disk space is free, and "
     "retry."),
    (38, "RemoteDisconnect", "Steam's servers dropped the connection.",
     "Retry."),
    (39, "ShoppingCartNotFound", "Shopping cart not found (store error, not Workshop related).", ""),
    (40, "Blocked", "The action was blocked.",
     "Check the account's restrictions and privacy settings."),
    (41, "Ignored", "The target is ignoring this account.", ""),
    (42, "NoMatch", "Nothing matched the request (for example no Workshop item with that ID).",
     "Check the Workshop ID; unlink it to publish a new item."),
    (43, "AccountDisabled", "The Steam account is disabled.",
     "Contact Steam Support."),
    (44, "ServiceReadOnly", "The Steam service is read-only right now (maintenance), so changes are refused.",
     "Wait and retry later. Steam's weekly maintenance is Tuesday afternoon (Pacific time)."),
    (45, "AccountNotFeatured", "The account is not featured.", ""),
    (46, "AdministratorOK", "Allowed only because the account is an administrator.", ""),
    (47, "ContentVersion", "The content version does not match what Steam expected.",
     "Retry; if it repeats, restart Steam / SteamCMD to pick up updates."),
    (48, "TryAnotherCM", "The Steam connection server is unavailable; the client should use another one.",
     "Retry; Steam reconnects to another server automatically."),
    (49, "PasswordRequiredToKickSession", "Another session is signed in and a password is needed to replace it.",
     "Sign in with the password instead of a cached login."),
    (50, "AlreadyLoggedInElsewhere", "The account is already signed in elsewhere.",
     "Close the other Steam/SteamCMD session, then retry."),
    (51, "Suspended", "The request or account is suspended.",
     "Check the account's standing at help.steampowered.com."),
    (52, "Cancelled", "The operation was cancelled.",
     "Retry the upload."),
    (53, "DataCorruption", "Data was corrupted in transit or on disk.",
     "Check the content files are not damaged and retry."),
    (54, "DiskFull", "A disk is full (usually the local one Steam stages the upload on).",
     "Free up disk space on the drive with Steam / SteamCMD and on the system drive, then retry."),
    (55, "RemoteCallFailed", "A call to a Steam back-end service failed.",
     "Retry later."),
    (56, "PasswordUnset", "The account has no password set.", "Set a password on the account."),
    (57, "ExternalAccountUnlinked", "An external account is not linked.", ""),
    (58, "PSNTicketInvalid", "The PSN ticket is invalid.", ""),
    (59, "ExternalAccountAlreadyLinked", "The external account is already linked elsewhere.", ""),
    (60, "RemoteFileConflict", "The Steam Cloud copy conflicts with the local copy.",
     "Resolve the Steam Cloud conflict in Steam, then retry."),
    (61, "IllegalPassword", "The password is not allowed.", ""),
    (62, "SameAsPreviousValue", "The new value is the same as the old one, so nothing changed.",
     "Nothing to fix: Steam already has this value."),
    (63, "AccountLogonDenied", "Sign-in needs a Steam Guard code (sent by e-mail).",
     "Enter the Steam Guard code from your e-mail and retry."),
    (64, "CannotUseOldPassword", "The new password is the same as the old one.", ""),
    (65, "InvalidLoginAuthCode", "The Steam Guard e-mail code is wrong.",
     "Enter the newest code from your e-mail exactly, then retry."),
    (66, "AccountLogonDeniedNoMail", "Sign-in needs a Steam Guard code, but the e-mail could not be sent.",
     "Check the account e-mail in Steam settings, or use the mobile authenticator."),
    (67, "HardwareNotCapableOfIPT", "Hardware is not capable of Intel IPT.", ""),
    (68, "IPTInitError", "Intel IPT initialisation failed.", ""),
    (69, "ParentalControlRestricted", "Steam Family View / parental controls block this.",
     "Unlock Family View in Steam, then retry."),
    (70, "FacebookQueryError", "A Facebook query failed.", ""),
    (71, "ExpiredLoginAuthCode", "The Steam Guard code has expired.",
     "Request a new code and enter it promptly."),
    (72, "IPLoginRestrictionFailed", "Sign-in from this IP address is restricted.",
     "Sign in from an allowed network, or lift the restriction in account settings."),
    (73, "AccountLockedDown", "The account is locked (suspected compromise).",
     "Recover the account through Steam Support."),
    (74, "AccountLogonDeniedVerifiedEmailRequired", "The account's e-mail must be verified before signing in.",
     "Verify the e-mail address in Steam account settings."),
    (75, "NoMatchingURL", "No matching URL.", ""),
    (76, "BadResponse", "Steam sent back a response that could not be understood.",
     "Retry; if it repeats, update Steam / SteamCMD."),
    (77, "RequirePasswordReEntry", "Steam needs the password entered again.",
     "Sign in again with the password."),
    (78, "ValueOutOfRange", "A value was outside the allowed range (for example visibility, or a too-large "
     "file).",
     "Check the visibility setting and the size of the content and preview files."),
    (79, "UnexpectedError", "Steam hit an unexpected internal error.",
     "Retry later."),
    (80, "Disabled", "The feature is disabled (for example Workshop uploads for this app).",
     "Nothing the toolbox can fix; retry later."),
    (81, "InvalidCEGSubmission", "Invalid CEG submission.", ""),
    (82, "RestrictedDevice", "This device is restricted from the action.", ""),
    (83, "RegionLocked", "The action is not available in this region.", ""),
    (84, "RateLimitExceeded", "Too many attempts in a short time; Steam is temporarily refusing requests "
     "(often from repeated failed sign-ins).",
     "Wait 30-60 minutes (sometimes longer) before trying again; retrying sooner resets the timer."),
    (85, "AccountLoginDeniedNeedTwoFactor", "Sign-in needs the Steam Guard mobile authenticator code.",
     "Enter the current code from the Steam mobile app, or approve the sign-in there."),
    (86, "ItemDeleted", "The Workshop item was deleted.",
     "Unlink the item in the toolbox and publish it as a new one."),
    (87, "AccountLoginDeniedThrottle", "Too many sign-in attempts; sign-in is throttled.",
     "Wait before trying to sign in again."),
    (88, "TwoFactorCodeMismatch", "The Steam Guard mobile code is wrong or out of date.",
     "Enter the current code from the Steam mobile app; check your PC clock is correct."),
    (89, "TwoFactorActivationCodeMismatch", "The two-factor activation code does not match.", ""),
    (90, "AccountAssociatedToMultiplePartners", "The account is associated with multiple partners.", ""),
    (91, "NotModified", "Nothing was modified.", ""),
    (92, "NoMobileDevice", "No mobile device is attached to the account.", ""),
    (93, "TimeNotSynced", "The time is not synchronised (Steam Guard codes depend on it).",
     "Sync your PC and phone clocks, then retry."),
    (94, "SmsCodeFailed", "The SMS code check failed.", "Request a new code."),
    (95, "AccountLimitExceeded", "Too many accounts use this resource.", ""),
    (96, "AccountActivityLimitExceeded", "Too many changes to this account recently.",
     "Wait and retry later."),
    (97, "PhoneActivityLimitExceeded", "Too many changes to this phone recently.", "Wait and retry later."),
    (98, "RefundToWallet", "Refund goes to wallet.", ""),
    (99, "EmailSendFailure", "Steam could not send an e-mail.", "Retry later."),
    (100, "NotSettled", "The payment has not settled yet.", ""),
    (101, "NeedCaptcha", "Steam wants a CAPTCHA solved.",
     "Sign in through the Steam client or website once, then retry."),
    (102, "GSLTDenied", "A game server login token was denied.", ""),
    (103, "GSOwnerDenied", "The game server owner was denied.", ""),
    (104, "InvalidItemType", "The item type is not valid for this action.",
     "Check the Workshop ID belongs to a Battlezone 98 Redux Workshop item."),
    (105, "IPBanned", "This IP address is banned.", "Contact Steam Support."),
    (106, "GSLTExpired", "The game server login token has expired.", ""),
    (107, "InsufficientFunds", "Insufficient funds.", ""),
    (108, "TooManyPending", "Too many requests are pending.", "Wait for earlier uploads to finish, then retry."),
    (109, "NoSiteLicensesFound", "No site licenses found.", ""),
    (110, "WGNetworkSendExceeded", "The WG network send limit was exceeded.", "Retry later."),
    (111, "AccountNotFriends", "The accounts are not friends.", ""),
    (112, "LimitedUserAccount", "This is a limited user account (it has not spent $5 on Steam), and limited "
     "accounts cannot publish.",
     "Spend at least $5 on Steam (or add funds) to lift the limit."),
    (113, "CantRemoveItem", "The item cannot be removed.", ""),
    (114, "AccountDeleted", "The account has been deleted.", ""),
    (115, "ExistingUserCancelledLicense", "The user cancelled the license.", ""),
    (116, "CommunityCooldown", "The account is in a Community cooldown (for example after a password or "
     "Steam Guard change) and cannot use Community features yet.",
     "Wait for the cooldown to end (Steam shows how long in the client), then retry."),
    (117, "NoLauncherSpecified", "No launcher was specified.", ""),
    (118, "MustAgreeToSSA", "The Steam Subscriber Agreement must be accepted first.",
     "Open the Steam client, accept the agreement it shows, then retry."),
    (119, "LauncherMigrated", "The launcher has migrated.", ""),
    (120, "SteamRealmMismatch", "The Steam realm (global vs. China) does not match.",
     "Use the Steam client for the realm the account belongs to."),
    (121, "InvalidSignature", "A signature is invalid.", "Retry; update Steam / SteamCMD."),
    (122, "ParseFailure", "Steam could not parse the request.",
     "Retry; check the title, description and tags for unusual characters."),
    (123, "NoVerifiedPhone", "The account has no verified phone number.",
     "Add and verify a phone number in Steam account settings."),
    (124, "InsufficientBattery", "The device's battery is too low.", ""),
    (125, "ChargerRequired", "The device must be charging.", ""),
    (126, "CachedCredentialInvalid", "The saved (cached) login is no longer valid.",
     "Sign in again with the password (and Steam Guard) to refresh it."),
    (127, "PhoneNumberIsVOIP", "The phone number is a VOIP number, which Steam does not accept.", ""),
    (128, "NotSupported", "This operation is not supported.", ""),
    (129, "FamilySizeLimitExceeded", "The Steam Family is full.", ""),
    (130, "OfflineAppCacheInvalid", "The offline app cache is invalid.", "Restart Steam online."),
]

ERESULTS = {code: SteamError(code, name, meaning, fix) for code, name, meaning, fix in _ERESULTS}

# Stage-specific meanings from the ISteamUGC documentation, where they differ
# from the general ones above.
_STAGE_MEANINGS = {
    ("create", 15): ("The account does not own a license for this game, or it has not accepted the Workshop "
                     "legal agreement.",
                     "Sign in with an account that owns Battlezone 98 Redux and accept the agreement at "
                     + WORKSHOP_LEGAL_URL + "."),
    ("create", 25): ("The account has reached its limit of Workshop items or Steam Cloud quota.",
                     "Delete unused Workshop items, then retry."),
    ("create", 29): ("The Steam client already has several item-creation requests outstanding.",
                     "Wait for them to finish, then retry."),
    ("submit", 15): ("Steam could not read or process the preview image, or the item belongs to another account.",
                     "Check the preview is a valid JPG/PNG/GIF under 1 MB, and that you are signed in with the "
                     "account that owns this item."),
    ("submit", 9): ("Steam could not find the content folder, the preview image, or the Workshop item.",
                    "Check both paths exist and the linked Workshop ID is still yours; unlink it to publish a "
                    "new item."),
}

# ESteamAPIInitResult, from SteamAPI_InitFlat.
STEAM_API_INIT_RESULTS = {
    0: ("OK", "Steam API started."),
    1: ("FailedGeneric", "Steam could not start the Steamworks API. Make sure Steam is running and signed in "
        "to an account that owns Battlezone 98 Redux."),
    2: ("NoSteamClient", "No running Steam client was found. Start Steam and sign in, then retry."),
    3: ("VersionMismatch", "The Steam client is older than the game's steam_api DLL. Let Steam update "
        "(restart it), then retry."),
}

# EItemUpdateStatus: where an interrupted upload stopped.
UPDATE_STATUS_STAGE = {
    0: "before it started",
    1: "while preparing the update",
    2: "while preparing the content",
    3: "while uploading the content",
    4: "while uploading the preview image",
    5: "while committing the changes",
}

# HTTP statuses from the Steam Web API.
HTTP_STATUS_TEXT = {
    400: "bad request: Steam rejected a parameter (Workshop ID, app ID or a field value)",
    401: "unauthorized: the Steam Web API key is missing or invalid",
    403: "forbidden: the Web API key is valid but not allowed to do this (tag updates need the game "
         "publisher's key)",
    404: "not found: the Workshop item or API method does not exist",
    405: "method not allowed: the request used the wrong HTTP method",
    408: "the request timed out",
    429: "rate limited: too many Steam Web API calls; wait a minute and retry",
    500: "Steam Web API internal error; retry later",
    502: "Steam Web API gateway error; Steam may be down, retry later",
    503: "Steam Web API unavailable (maintenance or overload); retry later",
    504: "Steam Web API gateway timeout; retry later",
}


def _normalise(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


_BY_NAME = {_normalise(e.name): e for e in ERESULTS.values()}
# SteamCMD's spelling of a few names.
_BY_NAME.update({
    "failure": ERESULTS[2],
    "failed": ERESULTS[2],
    "generic failure": ERESULTS[2],
    "invalidparameter": ERESULTS[8],
    "timedout": ERESULTS[16],
    "notloggedin": ERESULTS[21],
    "twofactorcodemismatch": ERESULTS[88],
    "accountlogindenied": ERESULTS[63],
    "accountlogindeniedneedtwofactor": ERESULTS[85],
    "ratelimited": ERESULTS[84],
})


def eresult_info(code_or_name):
    """The ``SteamError`` for an EResult number or name (``"Access Denied"``, ``"AccessDenied"``), or None."""
    if code_or_name is None:
        return None
    try:
        return ERESULTS.get(int(code_or_name))
    except (TypeError, ValueError):
        return _BY_NAME.get(_normalise(code_or_name))


def explain_eresult(code, stage=None):
    """``(name, meaning, fix)`` for an EResult, with stage-specific wording when known."""
    info = eresult_info(code)
    if info is None:
        return (f"Unknown ({code})",
                f"Steam returned EResult {code}, which this toolbox does not recognise.",
                "Retry; if it repeats, search for 'Steam EResult " + str(code) + "'.")
    meaning, fix = _STAGE_MEANINGS.get((stage, info.code), (info.meaning, info.fix))
    return info.name, meaning, fix


def describe_eresult(code, stage=None):
    """One paragraph a modder can act on, e.g. for an error dialog."""
    name, meaning, fix = explain_eresult(code, stage)
    action = {"create": "creating the Workshop item", "submit": "uploading the Workshop item",
              "update": "updating the Workshop item"}.get(stage, "the Workshop request")
    text = f"Steam rejected {action} (EResult {code}: {name}).\n{meaning}"
    if fix:
        text += f"\nWhat to do: {fix}"
    return text


def describe_init_result(code, detail=""):
    """Text for an ``ESteamAPIInitResult`` from ``SteamAPI_InitFlat``."""
    name, meaning = STEAM_API_INIT_RESULTS.get(int(code), (f"Unknown ({code})", "Steam API failed to start."))
    text = f"Steam API init failed ({name}). {meaning}"
    if detail:
        text += f"\nSteam said: {detail}"
    return text


def describe_http_status(status, eresult=None):
    """Text for a Steam Web API HTTP status, with its ``x-eresult`` header when present."""
    text = HTTP_STATUS_TEXT.get(int(status))
    if text is None:
        text = (f"Steam service error (HTTP {status})" if int(status) >= 500 else f"HTTP {status}")
    else:
        text = f"HTTP {status} {text}"
    if eresult not in (None, "", "1", 1):
        name, meaning, _fix = explain_eresult(eresult)
        text += f" [EResult {eresult} {name}: {meaning}]"
    return text


# SteamCMD messages that carry no EResult name, or need more context.
# (regex, title, meaning, fix)
STEAMCMD_PATTERNS = [
    (r"cached credentials not found|no cached credentials",
     "No saved SteamCMD login",
     "SteamCMD has no cached login for this account.",
     "Sign in once with your password and Steam Guard (Test Login in SETUP / ADVANCED), or publish with Steam "
     "running instead."),
    (r"login failure|failed to log ?in|invalid password",
     "SteamCMD sign-in failed",
     "SteamCMD could not sign in with the user name and password given.",
     "Check the user name and password. After several failures Steam rate-limits sign-ins; wait before retrying."),
    (r"steam guard code|two-factor code|enter the current code",
     "Steam Guard code needed",
     "SteamCMD is waiting for a Steam Guard code.",
     "Enter the code from your e-mail or the Steam mobile app in the Steam Guard box and retry."),
    (r"timeout uploading manifest|timed out uploading",
     "Upload timed out",
     "SteamCMD timed out sending the content to Steam. This is often a temporary Steam problem, or a very "
     "large upload on a slow connection.",
     "Retry. If it keeps happening, publish with the Steam client running (no SteamCMD) or try at another time."),
    (r"failed to create new workshop item",
     "Could not create the Workshop item",
     "Steam refused to create a new Workshop item.",
     "Check the account owns Battlezone 98 Redux and has accepted the Workshop agreement at "
     + WORKSHOP_LEGAL_URL + "."),
    (r"failed to commit",
     "Could not commit the update",
     "The content uploaded, but Steam refused to apply it to the item.",
     "Retry; check the item is still yours and was not deleted."),
    (r"content ?(root|folder).*(not found|doesn't exist|does not exist|empty)|no files (found|to upload)",
     "Content folder problem",
     "SteamCMD could not find files in the content folder.",
     "Check the content folder exists and contains your mod files."),
    (r"preview ?file.*(not found|doesn't exist|does not exist|too large)",
     "Preview image problem",
     "SteamCMD could not use the preview image.",
     "Check the preview exists and is a JPG/PNG/GIF under 1 MB."),
    (r"session replaced",
     "Session replaced",
     "The same account signed in elsewhere, which ends this session (SteamCMD and the Steam client sign each "
     "other out).",
     "Use either the Steam client or SteamCMD for publishing, not both at once; reconnect Steam and retry."),
    (r"not logged on|not logged in",
     "Not signed in",
     "SteamCMD was not signed in when it tried to upload.",
     "Sign in to SteamCMD first (Test Login in SETUP / ADVANCED)."),
    (r"no subscription|app .* not owned|missing configuration",
     "Game not owned",
     "This Steam account does not own Battlezone 98 Redux, so it cannot publish Workshop items for it.",
     "Sign in with an account that owns the game."),
    (r"disk (write )?failure|not enough (disk )?space|disk full",
     "Disk full",
     "SteamCMD ran out of disk space while staging the upload.",
     "Free space on the SteamCMD drive and retry."),
]

_EResultInParens = re.compile(r"\(([A-Za-z][A-Za-z0-9 \-']{1,60})\)")
_EResultNumber = re.compile(r"\beresult[ :=]*(\d{1,3})\b", re.IGNORECASE)


def diagnose_steamcmd_output(text, limit=5):
    """Explained problems found in SteamCMD console output or logs, newest last.

    Returns ``[{"title", "meaning", "fix", "line"}]`` with duplicates removed.
    """
    found, seen = [], set()

    def add(key, title, meaning, fix, line):
        if key in seen:
            return
        seen.add(key)
        found.append({"title": title, "meaning": meaning, "fix": fix, "line": line})

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        lower = line.lower()
        interesting = any(w in lower for w in ("error", "fail", "denied", "invalid", "timeout", "timed out",
                                                "not logged", "limit", "cached credentials", "steam guard",
                                                "session replaced", "banned", "not found"))
        if not interesting:
            continue
        named = False
        for match in _EResultNumber.finditer(line):
            info = eresult_info(match.group(1))
            if info and info.code != 1:
                add(("eresult", info.code), f"EResult {info.code}: {info.name}", info.meaning, info.fix, line)
                named = True
        for match in _EResultInParens.finditer(line):
            info = eresult_info(match.group(1))
            if info and info.code != 1:
                if info.code == 2 and "manifest" in lower:
                    continue   # the timeout pattern below explains it better
                add(("eresult", info.code), f"{match.group(1).strip()} (EResult {info.code})",
                    info.meaning, info.fix, line)
                named = True
        for pattern, title, meaning, fix in STEAMCMD_PATTERNS:
            if re.search(pattern, lower):
                add(("pattern", title), title, meaning, fix, line)
                named = True
                break
        if not named and ("error" in lower or "fail" in lower):
            add(("line", lower), "SteamCMD error", "SteamCMD reported an error this toolbox does not recognise.",
                "Open the SteamCMD logs for the full context.", line)
    return found[-limit:] if limit else found


def format_diagnoses(diagnoses):
    """Readable text for ``diagnose_steamcmd_output`` results."""
    blocks = []
    for d in diagnoses:
        text = f"- {d['title']}: {d['meaning']}"
        if d["fix"]:
            text += f"\n  What to do: {d['fix']}"
        text += f"\n  Log line: {d['line']}"
        blocks.append(text)
    return "\n\n".join(blocks)


# SteamCMD's exit codes are not documented. 0/1/7/8 are the ones it is known
# to use; for failed sign-ins it usually exits with the EResult itself
# (5 InvalidPassword, 63 AccountLogonDenied, 84 RateLimitExceeded, ...).
STEAMCMD_EXIT_CODES = {
    0: "SteamCMD finished without error.",
    1: "SteamCMD reported a general failure.",
    7: "SteamCMD stopped early, usually because it updated itself or could not start its first-run setup. "
       "Run it once on its own, then retry.",
    8: "SteamCMD failed during the upload.",
}


def describe_steamcmd_exit(code):
    """Text for a SteamCMD process exit code."""
    text = STEAMCMD_EXIT_CODES.get(code)
    if text is None and code is not None and code < 0:
        text = "SteamCMD was stopped or crashed before it finished."
    elif text is None and code in ERESULTS:
        name, meaning, fix = explain_eresult(code)
        text = f"This usually matches EResult {code} ({name}): {meaning}" + (f" What to do: {fix}" if fix else "")
    return f"SteamCMD exited with code {code}." + (f" {text}" if text else "")


# Messages from the Steamworks path (steamworks_helper.ps1 and
# steamworks_tags.py) that need explaining. (regex, meaning, fix)
STEAMWORKS_MESSAGES = [
    (r"SteamAPI_?Init(Flat)? failed|SteamAPI init failed",
     "The toolbox could not attach to the Steam client.",
     "Start Steam, sign in with the account that owns Battlezone 98 Redux, make sure it is online, and retry. "
     "If Steam is running as administrator, run the toolbox the same way (or neither)."),
    (r"not connected to Steam|NOT_LOGGED_ON",
     "Steam is running but offline or signed out.",
     "Go online in Steam (Steam > Go Online), then retry."),
    (r"SetItemTitle returned failure",
     "Steam refused the title (it is empty or longer than 128 characters).",
     "Shorten the title to 128 characters or fewer."),
    (r"SetItemDescription returned failure",
     "Steam refused the description (longer than 8000 characters).",
     "Shorten the description to 8000 characters or fewer."),
    (r"SetItemTags returned failure",
     "Steam refused the tags (a tag is too long, contains unusual characters, or there are too many).",
     "Keep tags short (under 255 characters) and use the standard Battlezone tags."),
    (r"SetItemContent returned failure",
     "Steam refused the content folder (it does not exist or is not a folder).",
     "Select an existing content folder."),
    (r"SetItemPreview returned failure",
     "Steam refused the preview image (it does not exist or cannot be read).",
     "Pick a JPG, PNG or GIF preview under 1 MB."),
    (r"SetItemVisibility returned failure",
     "Steam refused the visibility setting.",
     "Choose Public, Friends only, Hidden or Unlisted."),
    (r"StartItemUpdate returned an invalid handle",
     "Steam would not start an update for this item (wrong Workshop ID, or the item belongs to another game).",
     "Check the linked Workshop ID; unlink it to publish a new item."),
    (r"CreateItem returned an invalid call handle",
     "Steam would not start creating a new item.",
     "Make sure Steam is online and signed in, then retry."),
    (r"Timed out waiting for Steam to finish the (upload|item creation)|did not finish in time|Timed out waiting",
     "Steam stopped responding before the upload finished.",
     "Check Steam is still online and retry. Very large uploads on slow connections can take hours; keep the "
     "PC awake."),
    (r"I/O failure",
     "Steam reported a read/write or network I/O failure during the upload.",
     "Check the content folder is readable (no files open in other programs, drive still connected), that "
     "disk space is free, and retry."),
    (r"Could not load .*Win32 error",
     "Windows could not load the game's steam_api.dll.",
     "Verify the Battlezone 98 Redux game files in Steam, then retry."),
    (r"Steam did not provide",
     "The Steam client does not offer the Workshop interface the game DLL expects.",
     "Let Steam update (restart it), then retry."),
    (r"must run in 32-bit PowerShell|Steamworks helper exited with code",
     "The Steamworks helper could not run.",
     "Make sure Windows PowerShell is installed and not blocked by antivirus, or publish with SteamCMD."),
    (r"No Battlezone 98 Redux steam_api\.dll",
     "Neither the game nor the official uploader tool was found, so the toolbox has no steam_api.dll to use.",
     "Install Battlezone 98 Redux through Steam, or publish with SteamCMD."),
    (r"Steam is not running or not signed in",
     "", ""),
]


def explain_steamworks_message(message):
    """``message`` with the reason and the fix appended, when the toolbox knows them."""
    text = str(message or "")
    if "What to do:" in text:
        return text
    for pattern, meaning, fix in STEAMWORKS_MESSAGES:
        if re.search(pattern, text, re.IGNORECASE):
            if meaning:
                text += f"\n{meaning}"
            if fix:
                text += f"\nWhat to do: {fix}"
            break
    return text


def reference_entries():
    """``(heading, body)`` pairs covering every documented error, for the in-app reference."""
    entries = []
    for info in sorted(ERESULTS.values(), key=lambda e: e.code):
        body = info.meaning + (f"\nWhat to do: {info.fix}" if info.fix else "")
        entries.append((f"EResult {info.code}: {info.name}", body))
    for code, (name, meaning) in sorted(STEAM_API_INIT_RESULTS.items()):
        entries.append((f"Steam API init {code}: {name}", meaning))
    for _pattern, title, meaning, fix in STEAMCMD_PATTERNS:
        entries.append((f"SteamCMD: {title}", meaning + f"\nWhat to do: {fix}"))
    for code, meaning in sorted(STEAMCMD_EXIT_CODES.items()):
        entries.append((f"SteamCMD exit code {code}", meaning))
    for status, meaning in sorted(HTTP_STATUS_TEXT.items()):
        entries.append((f"Steam Web API HTTP {status}", meaning))
    for code, (name, meaning) in sorted(BAN_CHECK_RESULTS.items()):
        entries.append((f"Workshop item check {code}: {name}", meaning))
    entries.append(("Workshop item hidden by Steam", HIDDEN_ITEM_ADVICE))
    return entries


# EBanContentCheckResult: Steam's automated check of an item's text and
# files, reported as ``ban_text_check_result`` in the item details.
BAN_CHECK_RESULTS = {
    0: ("NotScanned", "Steam has not checked the item yet."),
    1: ("Reset", "Steam's check was reset and will run again."),
    2: ("NeedsChecking", "Steam's automated check is still reviewing the item; it may stay hidden until it "
        "finishes."),
    5: ("VeryUnlikely", "Steam's check found nothing wrong."),
    30: ("Unlikely", "Steam's check found nothing likely to be wrong."),
    50: ("Possible", "Steam's check flagged the item as possibly breaking Workshop rules."),
    75: ("Likely", "Steam's check flagged the item as likely breaking Workshop rules."),
    100: ("VeryLikely", "Steam's check flagged the item as very likely breaking Workshop rules."),
}

HIDDEN_ITEM_ADVICE = (
    "Updates still go through the Steam client (Publish with Steam running), the same way the official "
    "uploader does; the Web API cannot upload files. An update may restart Steam's check, so the item can stay "
    "hidden a while afterwards. If Steam hid it by mistake, appeal from the item's Workshop page or through "
    "help.steampowered.com.")


def item_moderation_status(details):
    """``{"state", "label", "message"}`` when Steam has an item hidden, banned or under review, else None.

    ``details`` is a Workshop item as GetUserFiles / GetDetails /
    GetPublishedFileDetails return it.
    """
    details = details or {}
    banned = str(details.get("banned", "")).strip().lower() in ("1", "true")
    reason = str(details.get("ban_reason") or "").strip()
    try:
        check = int(details.get("ban_text_check_result"))
    except (TypeError, ValueError):
        check = None
    if banned:
        message = "Steam has hidden this item from the Workshop" + (f": {reason}" if reason else ".")
        if check in BAN_CHECK_RESULTS and check >= 50:
            message += " " + BAN_CHECK_RESULTS[check][1]
        return {"state": "banned", "label": "Hidden by Steam", "message": message + "\n" + HIDDEN_ITEM_ADVICE}
    if check == 2:
        return {"state": "checking", "label": "Under Steam review",
                "message": BAN_CHECK_RESULTS[2][1] + "\n" + HIDDEN_ITEM_ADVICE}
    if check is not None and check >= 50:
        name, meaning = BAN_CHECK_RESULTS.get(check, (str(check), "Steam's check flagged the item."))
        return {"state": "flagged", "label": "Flagged by Steam",
                "message": meaning + " It may be hidden or removed.\n" + HIDDEN_ITEM_ADVICE}
    return None
