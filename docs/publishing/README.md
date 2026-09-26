# Battlezone Workshop Uploader

A desktop GUI for creating, updating, and validating Steam Workshop mods for **Battlezone 98 Redux**.

This tool is built around a folder-driven Workshop workflow:
- auto-detect SteamCMD and reuse a cached Steam login when available
- open or create a local upload profile by selecting a content folder
- load the complete set of owned Workshop items and explicitly link an existing item when needed
- scan the folder for common Battlezone content issues and review what changed since the last publish
- publish through your running Steam client (Steamworks), with no SteamCMD login, password or Steam Guard; SteamCMD with adaptive Steam Guard/mobile-approval handling is the fallback when Steam is not running

## Release Builds

Download the latest platform archive from the [Releases](https://github.com/GrizzlyOne95/Battlezone98Redux_WorkshopUploader/releases) page.

Executable names are intentionally stable and versionless:

- Windows: `BZWorkshopUploader.exe`
- Linux/macOS: `BZWorkshopUploader`

Release archives carry the version and platform, for example:

- `Battlezone98Redux_WorkshopUploader-v1.7.0-windows.zip`
- `Battlezone98Redux_WorkshopUploader-v1.7.0-linux.tar.gz`
- `Battlezone98Redux_WorkshopUploader-v1.7.0-macos.tar.gz`

Official Windows builds use the shared **Battlezone Modding Tools** product identity:

```text
FileDescription: Battlezone Workshop Uploader
ProductName: Battlezone Modding Tools
CompanyName: GrizzlyOne95
OriginalFilename: BZWorkshopUploader.exe
```

`FileVersion` and `ProductVersion` are derived from the release tag. Non-release CI builds use neutral `0.0.0` file metadata.

## Why Use This Instead Of The Old BZR Uploader?

- Uses the running Steam client when it can (like the official uploader tool), and SteamCMD otherwise.
- Does not force every upload public.
- Keeps local project state tied to Workshop IDs.
- Warns about common mod-breaking issues without hard-blocking every workflow.
- Can apply one-click fixes for several common file problems.

## Current Workflow

Run:

```bash
python uploader.py
```

Then use the workspace like this:

1. Start Steam and launch the uploader. With Steam running, Publish goes through your Steam client and needs no SteamCMD sign-in; SteamCMD, cached Steam authentication, and the Workshop owner are detected automatically for the fallback.
2. Select a content folder. Its **Local Upload Profile** opens automatically, or a new one is created for that folder.
3. To update an existing item, choose it from **Your Workshop Items** and click **USE ITEM** or **LOAD ITEM**. Leave the profile unlinked to create a new item.
4. Fill in preview, title, description, visibility, tags, and change note in the **Workshop Item Editor**.
5. Review **Readiness**. Clean content stays compact; warnings and fixable/blocking issues expand automatically.
6. Click `REVIEW AND PUBLISH`. Steam Guard fields or mobile-approval prompts appear only if Steam requires them.
7. Use **SETUP / ADVANCED** or **SHOW LOG** only when manual setup or diagnostics are needed.

## Main Features

### Local Upload Profiles

- One saved local upload profile per content folder under `profiles/`
- Folder selection automatically opens or creates the corresponding profile
- Automatic profile autosave while editing
- Persistent Workshop-item association by local content folder
- Last publish timestamp and changed-file tracking
- Selecting a folder here also makes it the toolbox project, so Overview, Validation and the other pages follow
- The content folder is watched automatically; readiness is rescanned when its files change

### Your Workshop Items

- Automatically refresh the owner's Workshop library when identity/API access is available
- Enumerate all owned items across Steam API pages instead of stopping at the first page
- Sort by title, Workshop ID, visibility or last update (click a column heading)
- Selecting an item shows its Steam preview thumbnail and current Steam tags
- Explicitly link the current upload profile to a selected Workshop item (the item's visibility is kept)
- Load Workshop details such as title, description, visibility and tags into the editor

### Safety And Validation

- ODF header and field validation using `odfHeaderList.txt` and `bzrODFparams.txt`
- Missing asset detection for `.odf` and `.material` references
- TRN duplicate `[Size]` detection
- TRN line-ending validation and correction
- Legacy `.map` file detection and cleanup
- Structure validation for required Battlezone content files

### Readiness Actions

- Open the selected file directly from a finding
- Apply selected one-click fixes
- Apply all available one-click fixes
- Inspect added, modified, and removed files since the last publish snapshot

### Publishing

- Automatic SteamCMD discovery with manual Browse/Auto-DL fallback
- Cached SteamCMD login detection with manual sign-in only when needed
- Adaptive Steam Guard code and Steam mobile-approval states
- QR account-verification helper
- SteamCMD VDF generation
- On an update, a blank description or preview image is left out of the upload, so Steam keeps the current one
- The review lists what an update would change on Steam (title, visibility) from the loaded library
- The preview is uploaded under a name derived from its content: Steam ignores a new preview that has the same file name as the last one, so this makes changed images update without renaming the file
- Expandable Steam/upload diagnostics rather than an always-visible raw log
- Content, title, description, visibility, preview and tags go to Steam in one Steamworks update through your Steam client, with upload progress in the activity log (SteamCMD cannot set tags, and the Steam Web API only accepts tag changes from the game's publisher)

### Analysis

- **SIZE / MEMORY ›** opens **Project › Dependencies**, which covers size on disk, texture memory
  (per mission and for the whole mod), non-DDS texture warnings and files nothing references

## Requirements

- Python 3.x
- Dependencies from `requirements.txt`
- Steam running and signed in (or SteamCMD, as the fallback)
- A Steam account that owns Battlezone 98 Redux

Install dependencies:

```bash
pip install -r requirements.txt
```

## Files Used By The App

- `uploader.py`: main application
- `project_store.py`: saved local upload-profile persistence
- `mod_scanner.py`: content scanning and validation
- `workshop_backend.py`: SteamCMD and Workshop API interactions
- `upload_preflight.py`: upload validation and VDF writing
- `steamworks_tags.py` / `steamworks_helper.ps1`: publishing, tags and previews through Steamworks
- `profiles/`: saved local upload-profile state

## Notes

- The app is primarily intended for Windows-based Battlezone modding workflows.
- Steam Web API features require an API key from `https://steamcommunity.com/dev/apikey`.
- Steamworks runs through the game's own `steam_api.dll` (or the official uploader tool's). The toolbox is 64-bit and that DLL is 32-bit, so it runs in the 32-bit Windows PowerShell (`steamworks_helper.ps1`), a fresh process per publish; a `steam_api64.dll` in the toolbox data folder, or the folder named by `BZ_STEAM_API_DIR`, is used in-process for tag and preview fixes only when no game DLL is found. Steam must be running and signed in to an account that owns Battlezone 98 Redux.
- Steam applies preview changes only from the app that created the item. Items made with the official **Battlezone 98 Redux - Uploader Tool** were created by that tool (app 450970), so SteamCMD, which runs as the game, reports their preview upload as OK while Steam keeps the old image. SteamCMD's login also signs a running Steam client out ("Session Replaced"), which is why Publish prefers the Steam client. After a publish the toolbox compares Steam's preview hash with the uploaded file and, if they differ, sets the preview through Steamworks as the item's creator app (tags too).

## License

MIT. See [LICENSE](LICENSE).
