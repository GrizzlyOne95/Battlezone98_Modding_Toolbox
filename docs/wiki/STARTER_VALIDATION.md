# Starter guide validation

Maintainer record for the seven starter tutorials. Checked on 23 October 2026 against **v0.1.30**, commit `9dd408c644eacf3a310de84edd02f7c89ef1cdff`. The diff from v0.1.29 to v0.1.30 contains documentation only; the application code is unchanged.

## Sources

The links below are pinned to the release checked.

| Tutorial | Source checked |
| --- | --- |
| Open and test a mod | [shell](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/app/shell.py), [project overview](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/app/pages/project.py), [validation](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/app/pages/validation.py), [Test in Game UI](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/app/pages/test_launch.py), [deployment and launch](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/launch.py) |
| Missing assets | [Dependencies UI](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/app/pages/dependencies.py), [asset graph](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/tree/v0.1.30/battlezone/assets) |
| Texture replacement | [Texture Manager UI and conversion](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/modules/textures/tex_man.py), [DDS codec](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/modules/textures/bcpack.py) |
| Stock extraction | [ZFS Explorer](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/modules/archives/zfs_page.py), [ZFS codec](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/battlezone/archives/zfs.py) |
| Unit edit | [ODF Explorer UI](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/app/pages/odf_explorer.py), [effective values](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/battlezone/odf/explorer.py), [loader semantics](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/docs/missions/ODF_VALIDATION_SCHEMA.md) |
| Radio voice line | [Audio UI](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/modules/audio/audio.py), [processing](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/modules/audio/processing.py) |
| Workshop publishing | [uploader and review UI](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/modules/publishing/uploader.py), [input preflight](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/modules/publishing/upload_preflight.py), [publish guard](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.30/bztoolbox/modules/publishing/publish_guard.py) |

## Executed application checks

The running Tk application used temporary Toolbox settings, a temporary project, and a temporary fake game installation. Stock data was read from the installed GOG Redux `bzone.zfs`; no game archives or existing user mods were changed. Paths from file dialogs were supplied by the check harness so the actual callbacks could run unattended.

- **Open/project/validation:** opened the temporary folder through the Shell. A small asset-mod INI plus the modified stock tank ODF passed the application's validation with zero errors, warnings or informational findings.
- **ZFS extraction:** opened the real stock archive, filtered to `avtank.odf`, selected it and called the page's Extract selected action. The extracted bytes matched the archive entry exactly. A screenshot of the running page was saved.
- **ODF edit:** changed the full stock `avtank.odf` from `maxHealth = 3000` to `4000`. The live ODF Explorer identified a stock replacement and reported 4000 in both its effective Fields data and Craft stats row. `classLabel` remained `wingman`.
- **Missing asset:** changed `weaponName1 = "gatstab"` to the deliberate typo `"gatstabb"`. The live Dependencies page listed `gatstabb.odf` as missing. Correcting the entry and rebuilding the graph removed that missing reference.
- **Test in Game:** selected a temporary fake Redux installation, `misn01.bzn`, the default windowed/skip-intro options, and deployment name `StarterTest`. The real Launch callback copied the project into the temporary install's `addon/StarterTest` directory. The launch function was replaced with a process stub; the captured command contained `/win`, `/nointro` and the mission name. Battlezone was not started. The screenshot shows this example configuration, not a gameplay test.
- **Textures:** called Process Single File through the running Texture Manager with synthetic 64 × 64 PNG inputs, rescaling disabled and mipmaps enabled. The opaque output was DDS/DXT1 with seven mip levels. The alpha example was DDS/DXT5. Both were written beside their source PNGs.
- **Audio:** ran the page's WAV processing method with generated test audio, Radio VO, light intensity, commbeep and no phaser/echo. The resulting file was in `bz98_radio_export`, mono, unsigned 8-bit PCM at 22050 Hz. The page's CSV export produced Filename/Duration/Type columns and the expected WAV entry. The completion popup was suppressed by the harness.
- **Workshop:** instantiated the actual page with authentication discovery, credentials, background watch and library refresh disabled for the check. Its real review-plan builder selected CREATE NEW for item ID 0 and UPDATE for a nonzero example ID. No test item was uploaded and no Steam authentication was performed.

The stock ODF was also inspected for its actual `[CraftClass] selectWaitMsg` entry, used by the radio tutorial. The documented trigger still needs testing with the user's recording in game. The guides do not claim that menu presence, mission balance or gameplay behavior was verified by these UI/file checks.

## Regression checks

```powershell
python -m pytest tests/app/test_launch.py tests/core/test_project.py tests/core/test_asset_graph.py tests/core/test_odf_explorer.py tests/app/test_odf_explorer_page.py tests/audio/test_processing.py tests/archives/test_zfs.py -q
```

Result: **63 passed**.

```powershell
python -c "import numpy, scipy; import pytest; raise SystemExit(pytest.main(['tests/publishing/test_publish_guard.py','tests/publishing/test_uploader.py','-q']))"
```

Result: **108 passed**. A plain invocation of this publishing subset initially produced one NumPy import-order failure on this Python 3.14 installation after the suite's headless GUI mocks were imported. Preloading NumPy/SciPy before collecting the subset avoided that environment issue. No application code was changed.

## Boundaries documented

- Deployment copies changes but does not remove stale destination files.
- The missing-file graph cannot classify every external model/texture as stock or missing.
- Single-file texture conversion ignores the batch output-folder setting and writes beside the source.
- The unit tutorial is a stock type replacement using a full ODF; it does not create an independent build-menu unit or rely on invented ODF inheritance.
- Audio conversion does not create a mission trigger, and its completion popup alone does not establish that every file succeeded.
- NEW CONTENT produces placeholders; a Workshop upload still needs real tested content.
- A nonzero Workshop ID selects an update target. Library refresh uses a Steam Web API key, separately from Steamworks publishing through the running client.

## Publication

Publish tutorial Markdown, `_Sidebar.md`, `_Footer.md` and `images/` to the separate GitHub wiki repository. Keep this record and `VALIDATION.md` in the main repository. The published image URLs use `raw.githubusercontent.com/wiki/...`.
