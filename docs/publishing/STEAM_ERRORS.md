# Steam Error Codes

Every error Steam can return to a Workshop upload, what it means for a Battlezone mod, and what to do.
The uploader shows these explanations in its error dialogs and activity log; **SETUP / ADVANCED › ERROR CODES** opens the same list, searchable, inside the toolbox.

The toolbox's copy of these explanations lives in `bztoolbox/modules/publishing/steam_errors.py`; a test checks every code there is listed here.

Steam reports failures in four shapes:

- **EResult** numbers, returned by Steamworks (publishing through the Steam client), printed by SteamCMD as their spaced name (`ERROR! Failed to update workshop item (Access Denied).`), and sent by the Steam Web API in its `x-eresult` header.
- **Steam API init results**, when the toolbox cannot attach to the Steam client.
- **SteamCMD messages and exit codes**. SteamCMD can exit with code 0 after an `ERROR!` line, so the toolbox also reads its logs after every upload.
- **HTTP statuses** from the Steam Web API (library, tag and preview checks).
- **Workshop item status**: an item Steam has hidden, banned or is still checking.

## EResult codes

Code 4 is not used by Steam. Codes without a "What to do" belong to other Steam features (store, trading, game servers) and are listed only so no code is ever shown unexplained.

| Code | Name | Meaning | What to do |
|---:|---|---|---|
| 0 | `None` | Steam returned no result at all. | Retry; if it repeats, restart Steam. |
| 1 | `OK` | Success. | — |
| 2 | `Fail` | Steam reported a generic failure without saying why. For Workshop uploads this usually means the Workshop servers had a problem, the content folder could not be read, or a SteamCMD manifest upload timed out. | Wait a few minutes and retry. Check that no file in the content folder is open in another program, and check https://steamstat.us for a Steam outage. |
| 3 | `NoConnection` | There is no connection to Steam (the client is offline or cannot reach the servers). | Check your internet connection, make sure Steam is online (not in Offline Mode), then retry. |
| 5 | `InvalidPassword` | The password is wrong, or the saved login is no longer valid. | Re-enter the password. If SteamCMD used a cached login, sign in again to refresh it. |
| 6 | `LoggedInElsewhere` | The same account is signed in somewhere else and that session blocks this one. | Close Steam or SteamCMD on the other machine or window, then retry. |
| 7 | `InvalidProtocolVer` | This Steam client or SteamCMD is too old for the Steam servers. | Let Steam / SteamCMD update itself (restart it), then retry. |
| 8 | `InvalidParam` | Steam rejected one of the values sent: usually the title (over 128 characters), the description (over 8000 characters), a tag, the visibility, the change note, or an empty/invalid content or preview path. | Shorten the title and description, remove unusual characters from tags, and check the content folder and preview image paths. |
| 9 | `FileNotFound` | Steam could not find something it needed: the content folder, the preview image, or the Workshop item itself (deleted, or the wrong Workshop ID). | Check the content folder and preview paths exist, and that the linked Workshop ID is still yours on Steam. Unlink the item to publish it as a new one. |
| 10 | `Busy` | Steam is busy with another request right now. | Wait a moment and retry. |
| 11 | `InvalidState` | The item or account is not in a state that allows this change (for example an update is already being processed for it). | Wait for any other upload of this item to finish, then retry. |
| 12 | `InvalidName` | A name was rejected (title or file name contains characters Steam does not accept). | Remove unusual characters from the title and from file names in the content folder. |
| 13 | `InvalidEmail` | The account's e-mail address is invalid. | Fix the account e-mail in Steam account settings. |
| 14 | `DuplicateName` | A name is already in use (often the preview file name matches an existing one). | Rename the preview image or retry; the toolbox renames previews by content to avoid this. |
| 15 | `AccessDenied` | Steam refused access. For Workshop uploads this means one of: the item belongs to another Steam account; the account does not own Battlezone 98 Redux; the preview image could not be read; or the Workshop legal agreement has not been accepted. | Sign in with the account that owns both the game and this Workshop item, check the preview image is a valid JPG/PNG/GIF, and accept the agreement at https://steamcommunity.com/sharedfiles/workshoplegalagreement. |
| 16 | `Timeout` | The operation took too long and Steam gave up. | Retry. Large uploads on slow connections can take a long time; avoid sleeping the PC mid-upload. |
| 17 | `Banned` | The account is banned: VAC, game, community or Workshop ban for this game. | Nothing the toolbox can fix; check the account's standing at help.steampowered.com. |
| 18 | `AccountNotFound` | The Steam account does not exist. | Check the user name. |
| 19 | `InvalidSteamID` | The Steam ID sent is not valid. | Check the Workshop owner / SteamID64 setting. |
| 20 | `ServiceUnavailable` | The Steam or Workshop service is down or overloaded. | Wait and retry later; check https://steamstat.us. |
| 21 | `NotLoggedOn` | Steam is not signed in. | Sign in to Steam (or SteamCMD), then retry. |
| 22 | `Pending` | The request is still being processed by Steam. | Wait a moment; if the item does not update, retry. |
| 23 | `EncryptionFailure` | Encryption or decryption failed while talking to Steam. | Retry; check the system clock is correct and nothing (proxy/antivirus) is intercepting Steam traffic. |
| 24 | `InsufficientPrivilege` | The account is not allowed to upload right now: a Workshop/community restriction, a locked account, or a limited (unpurchased) account. | Limited accounts must spend at least $5 on Steam before they can publish. Otherwise check the account's restrictions at help.steampowered.com. |
| 25 | `LimitExceeded` | A size or count limit was hit: most often the preview image is over 1 MB, or the account ran out of Steam Cloud/Workshop quota. | Make the preview image smaller than 1 MB (the toolbox can resize it), and delete unused Workshop items if you have many. |
| 26 | `Revoked` | Access (a license, key or session) was revoked. | Sign in again; check the account still owns the game. |
| 27 | `Expired` | A license, key or login session has expired. | Sign in again, then retry. |
| 28 | `AlreadyRedeemed` | The key was already redeemed. | — |
| 29 | `DuplicateRequest` | The same request was already sent and is still in progress. | Wait for the first upload to finish; do not publish the same item twice at once. |
| 30 | `AlreadyOwned` | The account already owns this. | — |
| 31 | `IPNotFound` | The IP address was not found. | Check your network connection. |
| 32 | `PersistFailed` | Steam failed to save the change on its servers. | Retry later. |
| 33 | `LockingFailed` | Steam could not lock the Workshop item for editing (another update holds it). | Wait for other uploads of this item (including from another PC or SteamCMD) to finish, then retry. |
| 34 | `LogonSessionReplaced` | The login session was replaced: the same account signed in elsewhere. SteamCMD signing in signs the Steam client out, and vice versa. | Reconnect Steam (or re-run SteamCMD) and retry; avoid running both with the same account at once. |
| 35 | `ConnectFailed` | Could not connect to Steam. | Check your internet connection and firewall, then retry. |
| 36 | `HandshakeFailed` | The secure connection to Steam could not be set up. | Retry; check the system clock and any proxy or antivirus intercepting traffic. |
| 37 | `IOFailure` | A read/write or network I/O error happened during the upload. | Check the content folder is readable and not on a disconnected drive, that disk space is free, and retry. |
| 38 | `RemoteDisconnect` | Steam's servers dropped the connection. | Retry. |
| 39 | `ShoppingCartNotFound` | Shopping cart not found (store error, not Workshop related). | — |
| 40 | `Blocked` | The action was blocked. | Check the account's restrictions and privacy settings. |
| 41 | `Ignored` | The target is ignoring this account. | — |
| 42 | `NoMatch` | Nothing matched the request (for example no Workshop item with that ID). | Check the Workshop ID; unlink it to publish a new item. |
| 43 | `AccountDisabled` | The Steam account is disabled. | Contact Steam Support. |
| 44 | `ServiceReadOnly` | The Steam service is read-only right now (maintenance), so changes are refused. | Wait and retry later. Steam's weekly maintenance is Tuesday afternoon (Pacific time). |
| 45 | `AccountNotFeatured` | The account is not featured. | — |
| 46 | `AdministratorOK` | Allowed only because the account is an administrator. | — |
| 47 | `ContentVersion` | The content version does not match what Steam expected. | Retry; if it repeats, restart Steam / SteamCMD to pick up updates. |
| 48 | `TryAnotherCM` | The Steam connection server is unavailable; the client should use another one. | Retry; Steam reconnects to another server automatically. |
| 49 | `PasswordRequiredToKickSession` | Another session is signed in and a password is needed to replace it. | Sign in with the password instead of a cached login. |
| 50 | `AlreadyLoggedInElsewhere` | The account is already signed in elsewhere. | Close the other Steam/SteamCMD session, then retry. |
| 51 | `Suspended` | The request or account is suspended. | Check the account's standing at help.steampowered.com. |
| 52 | `Cancelled` | The operation was cancelled. | Retry the upload. |
| 53 | `DataCorruption` | Data was corrupted in transit or on disk. | Check the content files are not damaged and retry. |
| 54 | `DiskFull` | A disk is full (usually the local one Steam stages the upload on). | Free up disk space on the drive with Steam / SteamCMD and on the system drive, then retry. |
| 55 | `RemoteCallFailed` | A call to a Steam back-end service failed. | Retry later. |
| 56 | `PasswordUnset` | The account has no password set. | Set a password on the account. |
| 57 | `ExternalAccountUnlinked` | An external account is not linked. | — |
| 58 | `PSNTicketInvalid` | The PSN ticket is invalid. | — |
| 59 | `ExternalAccountAlreadyLinked` | The external account is already linked elsewhere. | — |
| 60 | `RemoteFileConflict` | The Steam Cloud copy conflicts with the local copy. | Resolve the Steam Cloud conflict in Steam, then retry. |
| 61 | `IllegalPassword` | The password is not allowed. | — |
| 62 | `SameAsPreviousValue` | The new value is the same as the old one, so nothing changed. | Nothing to fix: Steam already has this value. |
| 63 | `AccountLogonDenied` | Sign-in needs a Steam Guard code (sent by e-mail). | Enter the Steam Guard code from your e-mail and retry. |
| 64 | `CannotUseOldPassword` | The new password is the same as the old one. | — |
| 65 | `InvalidLoginAuthCode` | The Steam Guard e-mail code is wrong. | Enter the newest code from your e-mail exactly, then retry. |
| 66 | `AccountLogonDeniedNoMail` | Sign-in needs a Steam Guard code, but the e-mail could not be sent. | Check the account e-mail in Steam settings, or use the mobile authenticator. |
| 67 | `HardwareNotCapableOfIPT` | Hardware is not capable of Intel IPT. | — |
| 68 | `IPTInitError` | Intel IPT initialisation failed. | — |
| 69 | `ParentalControlRestricted` | Steam Family View / parental controls block this. | Unlock Family View in Steam, then retry. |
| 70 | `FacebookQueryError` | A Facebook query failed. | — |
| 71 | `ExpiredLoginAuthCode` | The Steam Guard code has expired. | Request a new code and enter it promptly. |
| 72 | `IPLoginRestrictionFailed` | Sign-in from this IP address is restricted. | Sign in from an allowed network, or lift the restriction in account settings. |
| 73 | `AccountLockedDown` | The account is locked (suspected compromise). | Recover the account through Steam Support. |
| 74 | `AccountLogonDeniedVerifiedEmailRequired` | The account's e-mail must be verified before signing in. | Verify the e-mail address in Steam account settings. |
| 75 | `NoMatchingURL` | No matching URL. | — |
| 76 | `BadResponse` | Steam sent back a response that could not be understood. | Retry; if it repeats, update Steam / SteamCMD. |
| 77 | `RequirePasswordReEntry` | Steam needs the password entered again. | Sign in again with the password. |
| 78 | `ValueOutOfRange` | A value was outside the allowed range (for example visibility, or a too-large file). | Check the visibility setting and the size of the content and preview files. |
| 79 | `UnexpectedError` | Steam hit an unexpected internal error. | Retry later. |
| 80 | `Disabled` | The feature is disabled (for example Workshop uploads for this app). | Nothing the toolbox can fix; retry later. |
| 81 | `InvalidCEGSubmission` | Invalid CEG submission. | — |
| 82 | `RestrictedDevice` | This device is restricted from the action. | — |
| 83 | `RegionLocked` | The action is not available in this region. | — |
| 84 | `RateLimitExceeded` | Too many attempts in a short time; Steam is temporarily refusing requests (often from repeated failed sign-ins). | Wait 30-60 minutes (sometimes longer) before trying again; retrying sooner resets the timer. |
| 85 | `AccountLoginDeniedNeedTwoFactor` | Sign-in needs the Steam Guard mobile authenticator code. | Enter the current code from the Steam mobile app, or approve the sign-in there. |
| 86 | `ItemDeleted` | The Workshop item was deleted. | Unlink the item in the toolbox and publish it as a new one. |
| 87 | `AccountLoginDeniedThrottle` | Too many sign-in attempts; sign-in is throttled. | Wait before trying to sign in again. |
| 88 | `TwoFactorCodeMismatch` | The Steam Guard mobile code is wrong or out of date. | Enter the current code from the Steam mobile app; check your PC clock is correct. |
| 89 | `TwoFactorActivationCodeMismatch` | The two-factor activation code does not match. | — |
| 90 | `AccountAssociatedToMultiplePartners` | The account is associated with multiple partners. | — |
| 91 | `NotModified` | Nothing was modified. | — |
| 92 | `NoMobileDevice` | No mobile device is attached to the account. | — |
| 93 | `TimeNotSynced` | The time is not synchronised (Steam Guard codes depend on it). | Sync your PC and phone clocks, then retry. |
| 94 | `SmsCodeFailed` | The SMS code check failed. | Request a new code. |
| 95 | `AccountLimitExceeded` | Too many accounts use this resource. | — |
| 96 | `AccountActivityLimitExceeded` | Too many changes to this account recently. | Wait and retry later. |
| 97 | `PhoneActivityLimitExceeded` | Too many changes to this phone recently. | Wait and retry later. |
| 98 | `RefundToWallet` | Refund goes to wallet. | — |
| 99 | `EmailSendFailure` | Steam could not send an e-mail. | Retry later. |
| 100 | `NotSettled` | The payment has not settled yet. | — |
| 101 | `NeedCaptcha` | Steam wants a CAPTCHA solved. | Sign in through the Steam client or website once, then retry. |
| 102 | `GSLTDenied` | A game server login token was denied. | — |
| 103 | `GSOwnerDenied` | The game server owner was denied. | — |
| 104 | `InvalidItemType` | The item type is not valid for this action. | Check the Workshop ID belongs to a Battlezone 98 Redux Workshop item. |
| 105 | `IPBanned` | This IP address is banned. | Contact Steam Support. |
| 106 | `GSLTExpired` | The game server login token has expired. | — |
| 107 | `InsufficientFunds` | Insufficient funds. | — |
| 108 | `TooManyPending` | Too many requests are pending. | Wait for earlier uploads to finish, then retry. |
| 109 | `NoSiteLicensesFound` | No site licenses found. | — |
| 110 | `WGNetworkSendExceeded` | The WG network send limit was exceeded. | Retry later. |
| 111 | `AccountNotFriends` | The accounts are not friends. | — |
| 112 | `LimitedUserAccount` | This is a limited user account (it has not spent $5 on Steam), and limited accounts cannot publish. | Spend at least $5 on Steam (or add funds) to lift the limit. |
| 113 | `CantRemoveItem` | The item cannot be removed. | — |
| 114 | `AccountDeleted` | The account has been deleted. | — |
| 115 | `ExistingUserCancelledLicense` | The user cancelled the license. | — |
| 116 | `CommunityCooldown` | The account is in a Community cooldown (for example after a password or Steam Guard change) and cannot use Community features yet. | Wait for the cooldown to end (Steam shows how long in the client), then retry. |
| 117 | `NoLauncherSpecified` | No launcher was specified. | — |
| 118 | `MustAgreeToSSA` | The Steam Subscriber Agreement must be accepted first. | Open the Steam client, accept the agreement it shows, then retry. |
| 119 | `LauncherMigrated` | The launcher has migrated. | — |
| 120 | `SteamRealmMismatch` | The Steam realm (global vs. China) does not match. | Use the Steam client for the realm the account belongs to. |
| 121 | `InvalidSignature` | A signature is invalid. | Retry; update Steam / SteamCMD. |
| 122 | `ParseFailure` | Steam could not parse the request. | Retry; check the title, description and tags for unusual characters. |
| 123 | `NoVerifiedPhone` | The account has no verified phone number. | Add and verify a phone number in Steam account settings. |
| 124 | `InsufficientBattery` | The device's battery is too low. | — |
| 125 | `ChargerRequired` | The device must be charging. | — |
| 126 | `CachedCredentialInvalid` | The saved (cached) login is no longer valid. | Sign in again with the password (and Steam Guard) to refresh it. |
| 127 | `PhoneNumberIsVOIP` | The phone number is a VOIP number, which Steam does not accept. | — |
| 128 | `NotSupported` | This operation is not supported. | — |
| 129 | `FamilySizeLimitExceeded` | The Steam Family is full. | — |
| 130 | `OfflineAppCacheInvalid` | The offline app cache is invalid. | Restart Steam online. |

### Stage-specific meanings

Steam's Workshop documentation gives some codes a narrower meaning depending on whether the item was being created or updated:

| Stage | Code | Meaning | What to do |
|---|---:|---|---|
| create | 15 | The account does not own a license for this game, or it has not accepted the Workshop legal agreement. | Sign in with an account that owns Battlezone 98 Redux and accept the agreement at https://steamcommunity.com/sharedfiles/workshoplegalagreement. |
| create | 25 | The account has reached its limit of Workshop items or Steam Cloud quota. | Delete unused Workshop items, then retry. |
| create | 29 | The Steam client already has several item-creation requests outstanding. | Wait for them to finish, then retry. |
| submit | 9 | Steam could not find the content folder, the preview image, or the Workshop item. | Check both paths exist and the linked Workshop ID is still yours; unlink it to publish a new item. |
| submit | 15 | Steam could not read or process the preview image, or the item belongs to another account. | Check the preview is a valid JPG/PNG/GIF under 1 MB, and that you are signed in with the account that owns this item. |

## Steam API init results (`SteamAPI_InitFlat`)

| Code | Name | Meaning |
|---:|---|---|
| 0 | `OK` | Steam API started. |
| 1 | `FailedGeneric` | Steam could not start the Steamworks API. Make sure Steam is running and signed in to an account that owns Battlezone 98 Redux. |
| 2 | `NoSteamClient` | No running Steam client was found. Start Steam and sign in, then retry. |
| 3 | `VersionMismatch` | The Steam client is older than the game's steam_api DLL. Let Steam update (restart it), then retry. |

## Steam client (Steamworks) messages

| Message contains | Meaning | What to do |
|---|---|---|
| `SteamAPI_?Init(Flat)? failed\|SteamAPI init failed` | The toolbox could not attach to the Steam client. | Start Steam, sign in with the account that owns Battlezone 98 Redux, make sure it is online, and retry. If Steam is running as administrator, run the toolbox the same way (or neither). |
| `not connected to Steam\|NOT_LOGGED_ON` | Steam is running but offline or signed out. | Go online in Steam (Steam > Go Online), then retry. |
| `SetItemTitle returned failure` | Steam refused the title (it is empty or longer than 128 characters). | Shorten the title to 128 characters or fewer. |
| `SetItemDescription returned failure` | Steam refused the description (longer than 8000 characters). | Shorten the description to 8000 characters or fewer. |
| `SetItemTags returned failure` | Steam refused the tags (a tag is too long, contains unusual characters, or there are too many). | Keep tags short (under 255 characters) and use the standard Battlezone tags. |
| `SetItemContent returned failure` | Steam refused the content folder (it does not exist or is not a folder). | Select an existing content folder. |
| `SetItemPreview returned failure` | Steam refused the preview image (it does not exist or cannot be read). | Pick a JPG, PNG or GIF preview under 1 MB. |
| `SetItemVisibility returned failure` | Steam refused the visibility setting. | Choose Public, Friends only, Hidden or Unlisted. |
| `StartItemUpdate returned an invalid handle` | Steam would not start an update for this item (wrong Workshop ID, or the item belongs to another game). | Check the linked Workshop ID; unlink it to publish a new item. |
| `CreateItem returned an invalid call handle` | Steam would not start creating a new item. | Make sure Steam is online and signed in, then retry. |
| `Timed out waiting for Steam to finish the (upload\|item creation)\|did not finish in time\|Timed out waiting` | Steam stopped responding before the upload finished. | Check Steam is still online and retry. Very large uploads on slow connections can take hours; keep the PC awake. |
| `I/O failure` | Steam reported a read/write or network I/O failure during the upload. | Check the content folder is readable (no files open in other programs, drive still connected), that disk space is free, and retry. |
| `Could not load .*Win32 error` | Windows could not load the game's steam_api.dll. | Verify the Battlezone 98 Redux game files in Steam, then retry. |
| `Steam did not provide` | The Steam client does not offer the Workshop interface the game DLL expects. | Let Steam update (restart it), then retry. |
| `must run in 32-bit PowerShell\|Steamworks helper exited with code` | The Steamworks helper could not run. | Make sure Windows PowerShell is installed and not blocked by antivirus, or publish with SteamCMD. |
| `No Battlezone 98 Redux steam_api\.dll` | Neither the game nor the official uploader tool was found, so the toolbox has no steam_api.dll to use. | Install Battlezone 98 Redux through Steam, or publish with SteamCMD. |

## SteamCMD messages

Any `(Name)` in a SteamCMD error line is looked up in the EResult table above. These messages are recognised as well:

| Message | Meaning | What to do |
|---|---|---|
| No saved SteamCMD login | SteamCMD has no cached login for this account. | Sign in once with your password and Steam Guard (Test Login in SETUP / ADVANCED), or publish with Steam running instead. |
| SteamCMD sign-in failed | SteamCMD could not sign in with the user name and password given. | Check the user name and password. After several failures Steam rate-limits sign-ins; wait before retrying. |
| Steam Guard code needed | SteamCMD is waiting for a Steam Guard code. | Enter the code from your e-mail or the Steam mobile app in the Steam Guard box and retry. |
| Upload timed out | SteamCMD timed out sending the content to Steam. This is often a temporary Steam problem, or a very large upload on a slow connection. | Retry. If it keeps happening, publish with the Steam client running (no SteamCMD) or try at another time. |
| Could not create the Workshop item | Steam refused to create a new Workshop item. | Check the account owns Battlezone 98 Redux and has accepted the Workshop agreement at https://steamcommunity.com/sharedfiles/workshoplegalagreement. |
| Could not commit the update | The content uploaded, but Steam refused to apply it to the item. | Retry; check the item is still yours and was not deleted. |
| Content folder problem | SteamCMD could not find files in the content folder. | Check the content folder exists and contains your mod files. |
| Preview image problem | SteamCMD could not use the preview image. | Check the preview exists and is a JPG/PNG/GIF under 1 MB. |
| Session replaced | The same account signed in elsewhere, which ends this session (SteamCMD and the Steam client sign each other out). | Use either the Steam client or SteamCMD for publishing, not both at once; reconnect Steam and retry. |
| Not signed in | SteamCMD was not signed in when it tried to upload. | Sign in to SteamCMD first (Test Login in SETUP / ADVANCED). |
| Game not owned | This Steam account does not own Battlezone 98 Redux, so it cannot publish Workshop items for it. | Sign in with an account that owns the game. |
| Disk full | SteamCMD ran out of disk space while staging the upload. | Free space on the SteamCMD drive and retry. |

### SteamCMD exit codes

SteamCMD's exit codes are not documented by Valve. For failed sign-ins it usually exits with the EResult itself (5 `InvalidPassword`, 63 `AccountLogonDenied`, 84 `RateLimitExceeded`, ...), which the toolbox explains from the table above.

| Code | Meaning |
|---:|---|
| 0 | SteamCMD finished without error. |
| 1 | SteamCMD reported a general failure. |
| 7 | SteamCMD stopped early, usually because it updated itself or could not start its first-run setup. Run it once on its own, then retry. |
| 8 | SteamCMD failed during the upload. |

SteamCMD logs read after a failed upload: `workshopbuilds/depot_build_<appid>.log`, `logs/Workshop_log.txt`, `logs/console_log.txt` and `logs/stderr.txt` next to `steamcmd.exe`. Only lines written during the current upload are considered.

## Steam Web API HTTP statuses

| Status | Meaning |
|---:|---|
| 400 | bad request: Steam rejected a parameter (Workshop ID, app ID or a field value) |
| 401 | unauthorized: the Steam Web API key is missing or invalid |
| 403 | forbidden: the Web API key is valid but not allowed to do this (tag updates need the game publisher's key) |
| 404 | not found: the Workshop item or API method does not exist |
| 405 | method not allowed: the request used the wrong HTTP method |
| 408 | the request timed out |
| 429 | rate limited: too many Steam Web API calls; wait a minute and retry |
| 500 | Steam Web API internal error; retry later |
| 502 | Steam Web API gateway error; Steam may be down, retry later |
| 503 | Steam Web API unavailable (maintenance or overload); retry later |
| 504 | Steam Web API gateway timeout; retry later |

A write the Web API answers with HTTP 200 but a failing `x-eresult` header is reported as a failure with that EResult's explanation.

## Hidden, banned or under-review items

Steam's automated check can hide a Workshop item temporarily. The toolbox reads the item's `banned`, `ban_reason` and `ban_text_check_result` fields from Steam and shows the state:

- in the **Your Workshop Items** list (the Visibility column reads e.g. `Public · Hidden by Steam`) and in the selected item's details;
- in the publish review, before an update;
- in the result or error dialog after an upload to that item.

Updates still go through the Steam client (Publish with Steam running), the same way the official uploader does; the Web API cannot upload files. An update may restart Steam's check, so the item can stay hidden a while afterwards. If Steam hid it by mistake, appeal from the item's Workshop page or through help.steampowered.com.

| `ban_text_check_result` | Name | Meaning |
|---:|---|---|
| 0 | `NotScanned` | Steam has not checked the item yet. |
| 1 | `Reset` | Steam's check was reset and will run again. |
| 2 | `NeedsChecking` | Steam's automated check is still reviewing the item; it may stay hidden until it finishes. |
| 5 | `VeryUnlikely` | Steam's check found nothing wrong. |
| 30 | `Unlikely` | Steam's check found nothing likely to be wrong. |
| 50 | `Possible` | Steam's check flagged the item as possibly breaking Workshop rules. |
| 75 | `Likely` | Steam's check flagged the item as likely breaking Workshop rules. |
| 100 | `VeryLikely` | Steam's check flagged the item as very likely breaking Workshop rules. |
