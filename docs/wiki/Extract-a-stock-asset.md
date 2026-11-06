# Extract a stock asset

Use **Archives → ZFS Archives** to copy a file out of a game archive. Opening and extracting an archive does not modify the archive.

## Extract the stock tank ODF

1. Make a working folder outside the game installation, such as `C:\BZMods\StarterMod`.
2. Open **Archives → ZFS Archives** and select **Explorer**.
3. Click **Open archive…**.
4. Select `bzone.zfs` in your Battlezone 98 Redux installation folder.
5. Leave **Key override** empty and **Directory is encrypted** off for this stock archive.
6. Enter `avtank.odf` in **Filter**.
7. Select the matching row and click **Extract selected…**.
8. Choose your working folder. Confirm that `avtank.odf` appears there.
9. Open it in a text editor. Its `[GameObjectClass]` section should contain `classLabel = "wingman"` and `maxHealth = 3000` in the stock version checked for this guide.

<img src="https://raw.githubusercontent.com/wiki/GrizzlyOne95/Battlezone98_Modding_Toolbox/images/extract-stock-asset.png" width="440" alt="ZFS Explorer with the stock bzone.zfs archive filtered to avtank.odf">

This extraction was checked against the installed stock archive: the extracted file matched the archive entry byte for byte.

## Finding other files

**Filter** matches part of a filename. Try a basename or extension such as `.odf`, `.wav` or `.vdf`.

Not every asset is in `bzone.zfs`. Check the other archives in the installation, including the language-specific archives for localized content. Some Redux assets are loose files rather than ZFS members.

**Extract all…** extracts the whole archive, regardless of the current filter. For a small edit, use **Extract selected…**. Extract into a fresh folder so you do not mix originals with edited copies.

The archive may contain only one part of a unit's asset chain. An ODF can refer to weapons, a model, sounds and other files. Use **Dependencies** when preparing custom content.

[Home](Home) · [Next: change a unit](Change-a-unit)
