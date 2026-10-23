# Publish a first Workshop item

Start with content you have already [tested locally](Open-and-test-a-mod). Use a Steam account that owns Battlezone 98 Redux. On Windows, the Toolbox can publish through the running Steam client; SteamCMD is the fallback.

## Prepare the content folder

Upload the mod's content folder, not its parent folder or a ZIP. Include the files the mod needs. Keep recordings, art source files, backups and unrelated work outside it.

An asset-only replacement mod can use a root `StarterMod.ini` like this:

```ini
[DESCRIPTION]
missionName = "StarterMod"

[WORKSHOP]
mapType = "mod"
```

That small asset-mod setup was checked with the edited `avtank.odf` from the unit guide. An actual mission needs its own correct mission INI and world/BZN files. Do not turn a multiplayer or instant-action map into `mapType = "mod"` just to clear a finding.

**NEW CONTENT** creates a folder scaffold with placeholder map files. It does not produce a playable mission ready to upload.

## Create the item

1. Start Steam and sign in to the account that will own the item.
2. Open your working mod in the Toolbox, then open **Project → Workshop / Publish**.
3. Check **Content Folder**. Use **SELECT FOLDER** if needed.
4. Check that the editor is creating a new item. For a new item, **Workshop ID** is empty or `0`. A nonzero ID targets an existing item.
5. Set **Title**, **Description**, **Preview Image**, **Tags** and **Change Note**.
6. Set **Visibility** to **2 (Private)** for the first upload.
7. Click **RESCAN** and review **Readiness**. Open **DETAILS** to inspect findings. Fix problems in the content, then rescan.
8. Click **REVIEW AND PUBLISH**. If Steam connection or preflight errors appear, resolve them before continuing.
9. In the review, check the target, content folder, visibility, changed files and any proposed fixes.
10. Click **PUBLISH** when those details are correct. If the review offers **PUBLISH ANYWAY**, return to the findings and resolve the blockers first.
11. Wait for a successful result and a real Workshop item ID. Use **OPEN PAGE** to inspect the item on Steam.

If Steamworks publishing is unavailable, use **SETUP / ADVANCED** to configure the SteamCMD fallback and complete any Steam authentication prompts.

## Update the same item

1. Reopen the same local content folder/profile. Confirm its **Workshop ID** matches the published item.
2. If it is unlinked, find the item under **YOUR WORKSHOP ITEMS** and use **LOAD ITEM**. Confirm the item and content folder before linking. **LINK TO THIS FOLDER** also sets an upload target; it is not just a bookmark. If the library is unavailable, its refresh requires a Steam Web API key; you can instead enter the known item ID in **Workshop ID** and carefully verify the update target in the review.
3. Add your changed files and a change note. Click **RESCAN**.
4. Click **REVIEW AND PUBLISH**. The review must say it will **REPLACE the content** of the intended item ID.
5. Check visibility again, then publish.

Keep all required files in the content folder on every update. Do not switch to **NEW ITEM** to update an existing release; that creates a separate item.

After checking the private item and its content, you can change visibility and publish that update. The private upload does not prove the mod works on another player's installation.

The guide's UI and create/update review plans were checked without uploading a test item. No Steam login or live upload was performed during documentation validation.

[Home](Home) · [Open and test a mod](Open-and-test-a-mod)
