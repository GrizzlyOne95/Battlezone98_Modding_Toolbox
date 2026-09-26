# Battlezone BZN Toolbox

> Formerly **Battlezone BZN Scanner** (`BZBZNScanner.exe`, repository `Battlezone98Redux_BZN_Scanner`). Old GitHub links redirect here.

A Battlezone 98 Redux BZN toolbox: mission preflight plus BZ2/BZCC map porting. It scans ASCII or binary `.BZN` files for referenced ODFs, classifies them as stock/custom, checks custom dependencies, and validates local or packaged ODF files against known Redux loader behavior.

<img width="802" height="632" alt="Battlezone BZN Toolbox" src="https://github.com/user-attachments/assets/5fc44ce6-5d20-45b0-8089-e2d475c86ea7" />

## Release builds

Download the latest platform archive from the Releases page. Executable names are intentionally stable and versionless:

- Windows: `BZBZNToolbox.exe`
- Linux/macOS: `BZBZNToolbox`

Release archives carry the version, for example `Battlezone98Redux_BZN_Toolbox-v1.2.3-windows.zip`.

Official Windows builds use the shared Battlezone Modding Tools product identity:

```text
FileDescription: Battlezone BZN Toolbox
ProductName: Battlezone Modding Tools
CompanyName: GrizzlyOne95
OriginalFilename: BZBZNToolbox.exe
```

`FileVersion` and `ProductVersion` are derived from the Git release tag.

## Scan modes

The integrated GUI supports four entry points:

- **Load BZN** - scan mission ODF dependencies and validate ODFs beside the BZN.
- **Scan ODF Folder** - validate every ODF in a mod/work folder without requiring a BZN.
- **Scan ZIP** - validate ODFs directly inside a packaged ZIP without extracting it first.
- **BZCC to Redux Port** - convert a BZ2/BZCC BZN using an ASCII Redux template, with ODF/team maps, terrain offset report, and optional class checks.

## BZN Dependencies

- Reads both ASCII and binary Redux BZN files.
- Extracts referenced ODF names from mission data.
- Separates stock and custom ODFs.
- Checks whether required custom ODF files are present beside the BZN.
- Handles local ODF filename matching case-insensitively, matching normal Windows mod-folder behavior.

## ODF Validation

The **ODF Validation** tab is read-only: the validator reports findings and suggested fixes but never rewrites mission files. Findings include severity, file, line number where available, section/key, stable rule ID, suggested fix, and structured evidence IDs/source details.

Validation is driven by `odf_schema.py` rather than hard-coding every special case into the parser. Rules combine `classLabel` with the class sections physically present in the ODF so the checker can distinguish loader paths that reuse similar legacy names.

### `baseName` selects a base/prototype; it is not ODF file inheritance

Recovered loader mining changed the model here. Canonical `baseName` has a real code reader, but that reader does **not** open another `.odf` and merge its sections/keys into the child. Defaults come from the engine's base/prototype/class chain.

Consequences for the validator:

- `baseName = "foo"` does **not** mean `foo.odf` must exist beside the child.
- The validator does not inherit `classLabel`, sections, or keys from `foo.odf`.
- Cross-references through `baseName` do not form ODF file cycles.
- A duplicate `foo.odf` filename does not make `baseName = "foo"` ambiguous file inheritance.
- Missing/empty `baseName` means this field selects no base prototype, but that is **not automatically invalid** for every ODF. A class-specific warning should only be added when code proves that a particular loader requires a base prototype.
- Lowercase `basename` remains distinct from canonical `baseName`; the validator does not invent a global case-insensitivity rule.

The current evidence-backed schema covers the failure family exposed by the legacy **AbsoZero** mission plus additional mined loader mismatches:

- **CRITICAL:** `classLabel = "flare"` using `[FlareBuildingClass]` instead of Redux `[FlareMineClass]`. The legacy section has no loader reader; `payloadName` can remain null and the flare firing path can fault while building the payload ordnance.
- **CRITICAL:** canonical `[FlareMineClass]` with no `payloadName`.
- **ERROR:** legacy `[GameObject]` where Redux dispatch expects `[GameObjectClass]`.
- **ERROR:** magnet mine/ordnance ODFs using `[MagnetClass]` instead of `[MagnetMineClass]`.
- **ERROR:** magnet mine `triggetDelay` typo instead of `triggerDelay`.
- **ERROR:** scavenger objects using `[ScavengerCraftClass]` instead of `[ScavengerClass]`.
- **ERROR/WARNING:** `classLabel = "flamepuff"` using legacy `[flameClass]` and unsupported fields such as `flameLength`, `variance`, and `shotColor`.
- **WARNING:** `flameDelay` in `[FlamePuffClass]`; recovered code reads `frameDelay` instead.
- **ERROR:** `classLabel = "explosion"` + `[OrdnanceClass]` using legacy `[Explosion]`; Redux reads explosion-specific fields from `[ExplosionClass]`, so keys under `[Explosion]` are not consumed by that loader.
- **ERROR:** building ODFs using the exact stock typo `[SprayBuildngClass]`; recovered code reads `[SprayBuildingClass]`, and the typo has no recovered reader. The mining audit found the bad spelling in four stock spray-building ODFs.
- **WARNING:** missing/misspelled `xplGround`, `xplVehicle`, and `xplBuilding` ODF references, checked against both local and stock ODF names. This catches errors such as `xmlasbld` vs `xlasbld` without flagging valid stock assets as missing.

Rules are intentionally context-sensitive. The validator does **not** blindly rename every similar-looking section: magnet, flame, explosion, and spray-building diagnostics are constrained to the surrounding class/section evidence recovered for those loader paths.

## Provenance model

Structured evidence lives in `odf_evidence.py`. Evidence records can identify the evidence kind, confidence, recovered function/address, repository/path when actually verified, stock examples, runtime reproductions, and a concise statement of what the evidence proves.

Confidence vocabulary:

- `confirmed-code` - behavior directly recovered from loader/decomp code.
- `code+stock` - code behavior corroborated by stock content or runtime reproduction.
- `stock-only` - observed in stock content but not yet code-proven.
- `inferred` - research lead only; never enough by itself for a hard validator rule.

Redux executable addresses are kept distinct from BZ1_Source corroboration. The validator does not claim a BZ1_Source file path for a Redux address unless that exact path has been independently verified.

The flare crash rule carries the recovered chain:

`FlareMineClass::Load 0x004D2B10 -> FlareMine::Update 0x004D2E90 -> OrdnanceClass::Build 0x00586FF0`

with the confirmed null dereference at `0x00586FFC`.

Research output is **not automatically validator policy**. Hash-only, name-unresolved, inferred, and stock-only discoveries remain research data until reviewed and promoted deliberately.

See [`docs/ODF_VALIDATION_SCHEMA.md`](docs/ODF_VALIDATION_SCHEMA.md) for the schema contract and evidence policy.

## Command-line ODF validation

The same validator can be used without the GUI:

```bash
python odf_validator.py path/to/mod-folder
python odf_validator.py path/to/mod.zip
python odf_validator.py path/to/file.odf
python odf_validator.py path/to/mod.zip --json
```

Exit codes are suitable for automation: `0` for warnings/no findings, `1` when errors are present, and `2` when a Critical crash-risk finding is present.

## BZ2/BZCC to Redux BZN port

`bzcc_port.py` ports BZ2/BZCC BZN objects, paths and AOIs into a Battlezone 98
Redux BZN by cloning Redux prototype records, and moves them onto the terrain
produced by the WorldBuilder BZ2 terrain port:

The **BZCC to Redux Port** GUI tab exposes the same conversion. Select the
source BZN, an ASCII Redux template containing the needed object prototypes,
and an output BZN. Use the ODF and team mapping JSON files where needed. Select
the WorldBuilder terrain report to apply its `object_offset_m`; the manual X/Y/Z
offset fields are an alternative. A conversion report records substitutions,
skips, and applied team mappings. **Scan output** opens the new BZN in the
dependency scanner.

```bash
python bzcc_port.py source.bzn redux_template.bzn out.bzn --map odf_map.json --offset-from NAME_port.json
```

Add `--source-odfs` and `--redux-odfs` to run the class check. It diffs each BZCC
`classLabel` chain against valid Redux classes and refuses prototypes whose BZN
records do not match. `class_labels.py` runs the same check on its own.
See [`docs/BZCC_TO_BZR_PORT.md`](docs/BZCC_TO_BZR_PORT.md).

## Battlezone 1.5 ↔ Redux BZN conversion

**Missions › 1.5 ↔ Redux BZN** in the toolbox, or on the command line:

```
bztoolbox bzn convert mission.bzn --to 1.5            # -> mission_v1045.bzn
bztoolbox bzn convert mission.bzn --to redux --binary # -> mission_v2016.bzn, binary
bztoolbox bzn convert *.bzn --out-dir out/ --odf-dir mymod/ --report changes.json
```

Battlezone 1.5 writes BZN version 1045 (1037-1044 from older patches); Redux
writes 2016. It is one format whose fields are gated on the version, so a
conversion is a re-save at the other version. `battlezone/bzn/bz1.py` is a
port of the Battlezone 1 half of BZNParser (BZNTools, MIT): every class schema
there is one function walking its fields with the same `version` gates as
BZNParser's `Hydrate`/`Dehydrate` pair, used by both the reader and the writer.
It reads ASCII and binary files from version 1022 on and writes both.

Between 1045 and 2016 the fields that differ are:

| Field | Versions | Conversion |
| --- | --- | --- |
| `isCritical` (every object) | 1046-1999, >= 2010 | dropped / added as `false` |
| `cloakState`, `cloakTransBeginTime`, `cloakTransEndTime` (craft) | >= 2000 | dropped / added as 0 |
| `lastRecycled` (constructionrig) | >= 2001 | dropped / added as 0 |
| `portalState`, `portalBeginTime`, `portalEndTime`, `isIn` (portal) | >= 2004 | dropped / added as 0 |
| `AiCmdInfo.param` | LONG < 2012, 8-byte ID >= 2012 | BZNParser's UInt64: the ID bytes read little-endian; an ODF name has no LONG form |
| `AiPath.old_ptr` | raw bytes <= 2011, pointer > 2011 | the pointer is the bytes read little-endian (`4075E100` <-> `00e17540`) |
| pointers in binary files | 4 bytes < 2012, 8 bytes >= 2012 | value kept |
| `undefbool` after a Lua mission name | 1044 maps only | play state, not map content |

A value that is not the default and has no field at the target, an `ID`
longer than the 8 bytes 1.5 (or any binary file) can store, or a `param` that
names an ODF is a *loss*: the conversion is refused and the losses listed,
unless `--allow-loss` is given. Everything else is listed as added, dropped
or converted. The output is re-read and every field not in that list is
compared with the source before anything is written.

`missionSave` is written `true` for a mission map, as BZNParser does: the 1.5
loader treats `false` as a shell save game.

Object classes are not stored in BZNs. They come from BZNParser's stock table
(`battlezone/bzn/data/bz1_class_labels.txt`), from the `classLabel` of the
ODFs under `--odf-dir`, or, for unknown ODFs, from the editor's
`<odf><n>_<classLabel>` object label; failing all of those every class is
tried and the shortest parse that lets the next object parse wins
(BZNParser's rule). When the remaining candidates would write differently at
the target version the result warns and names the object.

Formatting: a file rewritten at its own version is byte-identical to the
source (spelling of numbers, pointer widths, garbage in binary type words and
all). `--normalize` formats every value as BZNParser does instead. Binary to
ASCII keeps six significant digits, as the games' own ASCII saves do.

Verification: all 63 1.5 BZNs in a 1.5 install (1037-1045, 48 of them binary) and
361 Redux BZNs (1022-2016) parse; with `--normalize` every conversion to 2016
and to 1045 is byte-identical to BZNParser's output for the same file, and the
converted 1.5 maps re-parse with BZNParser as 2016 with the same object
classes. The ten `bz64port` missions go 2016 -> 1045 -> 2016 back to their
original bytes.

## Rule policy

ODF checks should be traceable to at least one of:

1. Redux loader/decomp behavior,
2. a stock Redux ODF contract, or
3. a reproducible runtime failure.

The goal is a codebase-rooted ODF preflight schema rather than a generic INI spell-checker. Unknown sections/keys are not automatically rejected while the schema is incomplete.

## Development

Run the regression suite with:

```bash
python -m unittest discover -s tests -v
```

The test suite includes minimized AbsoZero regression cases, false-positive controls, ZIP scanning, baseName non-file-inheritance regressions, mined-loader rules, and structured provenance checks. The release workflow runs the tests before packaging the integrated `toolbox_app.py` front end for Windows, Linux, and macOS.
