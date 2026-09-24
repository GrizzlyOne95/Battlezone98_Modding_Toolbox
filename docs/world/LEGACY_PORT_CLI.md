# Legacy Map Port CLI

WorldBuilder includes console and GUI paths for Battlezone 1.x to Battlezone 98 Redux map ports.

## Convert one mission folder

Extract the old map archive first, then run:

```powershell
.\world-builder-cli.exe legacy-port "<legacy-map-folder>" "<redux-output-folder>"
```

For a folder containing exactly one BZN, the atlas/material prefix defaults to the BZN stem. Override it with `--prefix` when needed. The palette referenced by the TRN is resolved automatically from the map or the embedded stock ACT set; `--palette` is available as a manual override.

The command runs the same Legacy Atlas, HGT conversion, and package finalizer used by the GUI, then runs launchability preflight. Exit code `0` means the package passed launch-critical checks. Exit code `2` means conversion completed but preflight found blocking errors.

The output includes the converted HG2, complete TRN, Redux INI, MAT/LGT companions, atlas/CSV/material assets, converted custom sky assets, resolved ACT palette, support files, optional preview PNG, `legacy_port_report.txt`, and `legacy_port_report.json`.

Legacy `.MAP` files are conversion inputs only and are not copied into the Redux launch folder. Terrain MAPs are packed into the generated atlas. Custom sky/cloud/star MAPs are converted to PNG/DDS plus Ogre material files. TRN `.MAP` tokens are retained because Redux resolves them as material names; the original indexed `.MAP` bytes are not required at runtime.

## Batch port a parent folder

For bulk conversion, put each legacy mission package in its own immediate subfolder:

```text
C:\BZ_Legacy_Maps\
├─ Legends\
│  ├─ legends.bzn
│  ├─ legends.trn
│  ├─ legends.hgt
│  └─ ...
├─ Scrapland\
│  ├─ scrapland.bzn
│  └─ ...
└─ AnotherMap\
   ├─ another.bzn
   └─ ...
```

Then run:

```powershell
.\world-builder-cli.exe legacy-port-batch `
    "C:\BZ_Legacy_Maps" `
    "C:\BZ_Redux_Maps"
```

Batch mode processes **immediate subfolders only**. A child folder is treated as a mission package when it directly contains at least one `.BZN`. Non-mission child folders are skipped and listed in the batch report.

Each mission is isolated from every other mission: palette resolution, terrain conversion, atlas creation, package finalization, and preflight all run against that mission's own source folder. A failed or malformed mission does **not** stop the batch; WorldBuilder records the failure and continues with the next folder.

The output root receives one same-name subfolder per source mission plus:

- `legacy_batch_report.txt`
- `legacy_batch_report.json`

The batch command returns exit code `0` only when every discovered mission passes preflight. It returns `2` when the batch completes but one or more missions are not launch-ready.

By default each mission resolves its own TRN-declared palette independently. `--palette` is available as an explicit override applied to every mission in the batch, but should only be used when that is intentional.

## GUI batch mode

The **Legacy Atlas** tab also contains **Batch Port Mission Folders**. Select:

1. a source parent folder whose immediate subfolders each contain a legacy mission package;
2. a separate Redux output parent folder;
3. optionally enable the checkbox to apply the currently selected manual ACT palette to every mission.

Click **BATCH PORT SUBFOLDERS**. The GUI uses the same single-map worker and validation path as the CLI, continues past failed maps, and writes the same parent-level batch report.

## Validate an existing output

```powershell
.\world-builder-cli.exe validate-port "<legacy-map-folder>" "<redux-output-folder>"
```

Use `--no-prepare` for validation without emitting the resolved ACT or preview helper files.

## Preflight checks

The validator checks BZN/INI presence, TRN geometry, HG2 dimensions, MAT size/material range, classic and Redux LGT layouts, the atlas material/CSV/texture chain, custom runtime dependencies, generated material-name case, and palette resolution. Stock/external dependencies not bundled with the map are reported as warnings rather than fabricated.
