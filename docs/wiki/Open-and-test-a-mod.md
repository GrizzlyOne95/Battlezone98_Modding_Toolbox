# Open a mod and test it

Start with a working mod or mission. This guide opens its folder, checks it, and copies it into the game's addon folder for testing.

## Open the working folder

1. Copy the mod into a working folder outside the game installation, for example `C:\BZMods\StarterMod`.
2. Keep the mod's files directly inside that folder. Select the content folder, not a parent folder containing several mods.
3. In the Toolbox, click **Open mod folder…** and choose it.
4. Open **Project → Overview**. Check the folder path and file/mission counts.

Opening a folder creates a local Toolbox profile. It does not create a playable mission or change the mod's files.

If you are starting from scratch, [Make a playable map](Make-a-playable-map) creates a complete map folder: terrain, mission and INI.

## Check the files

1. Open **Project → Validation**.
2. Click **Run validation** and wait for the results.
3. Select a finding to read its file, location and explanation. **Open file** opens the referenced file; **Show file in folder** reveals it.
4. Correct errors in your working copy, then run validation again.

Some findings have **Apply fix**. Read the proposed fix before applying it. A missing asset usually needs the correct file or reference; see [Fix a missing asset](Fix-a-missing-asset).

## Launch a test

1. Open **Project → Test in Game**.
2. Select the correct **Game** installation. If it is missing, click **Other…** and select the folder containing `battlezone98redux.exe`.
3. Under **Mission**, choose a BZN from your project. You can also enter a stock mission such as `misn01.bzn` to test an asset replacement. Leaving this field empty starts the game at its menu.
4. Leave **Windowed** and **Skip intro movie** selected for a quick test. Leave **Extra arguments** empty initially.
5. Keep **Copy the project into addon\** selected. Use a distinct folder name such as `StarterTest`.
6. For a map, with copying selected, **Test the map as** can deploy it for Instant Action (**offline**) or the Multiplayer menu (**multiplayer**); see [Make a playable map](Make-a-playable-map#test-it).
7. Check **Command**. It shows the destination folder and launch command.
8. Click **Launch**.
9. Test the change, close the game, and read **RUN**. Click **Read logs now** if needed. When launching through Steam, use **Read logs now** after finishing the test.

<img src="https://raw.githubusercontent.com/wiki/GrizzlyOne95/Battlezone98_Modding_Toolbox/images/test-in-game.png" width="440" alt="Test in Game page showing mission, options, deployment folder, command and launch controls">

The screenshot uses example project and game paths. The verification used a temporary game folder and checked the launch command without starting Battlezone.

## Keep editing the source folder

The deployed copy lives at `<game>\addon\StarterTest`. Continue editing your working folder and launch again to copy changed files.

Deployment does **not** remove old files from the destination. If you rename or delete an asset in the source, remove its stale deployed copy too. **Remove deployed copy** removes that deployment folder; check the name before using it. If your working folder is already the destination addon folder, turn off copying.

Errors in a log are clues, not a complete test result. Check the actual mission, models, textures and sounds in game.

[Home](Home) · [Next: fix a missing asset](Fix-a-missing-asset)
