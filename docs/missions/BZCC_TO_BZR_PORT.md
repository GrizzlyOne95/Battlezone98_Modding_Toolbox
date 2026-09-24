# BZ2/BZCC to Battlezone 98 Redux BZN port

Part of the Battlezone BZN Toolbox. Run it from the repository root.

`bzcc_port.py` is a standalone Python 3.10+ command line utility. It transfers
object transforms, teams, labels, paths, AOIs and the terrain reference from a
Battlezone II or Battlezone Combat Commander BZN into a Battlezone 98 Redux
BZN. It reads ASCII sources and binary BZ2/BZCC sources version 1103 or newer.
It uses only the Python standard library.

It is the BZN half of a BZCC to Redux map port. The terrain half (TER to
HG2/MAT/atlas/TRN) is `bz2_terrain_bundle.py` in
[Battlezone98Redux_WorldBuilder](https://github.com/GrizzlyOne95/Battlezone98Redux_WorldBuilder)
(branch `feature/bz2-to-bzr-terrain-port`).

## How it works

The source games and Redux use different object layouts. The converter takes
an **ASCII Redux BZN template** with at least one placed example of every
Redux object type you want to create. It clones the appropriate Redux record
and replaces its ODF (`PrjID`), position, orientation, team, label, player flag
and sequence numbers. All other per-object state comes from that Redux record.
The prototypes are removed from the output.

## Usage

The toolbox GUI has a **BZCC to Redux Port** tab with source/template/output
pickers, mapping files, terrain report offset, conversion report, and class
check options. The **Scan output** button opens the generated BZN in the
dependency scanner. The equivalent command line is:

```text
python bzcc_port.py source.bzn redux_template.bzn out.bzn \
    --map odf_map.json --mission LuaMission \
    --offset-from isdf01_port.json \
    --team-map docs/examples/isdf01_team_mapping.json \
    --report port_report.json
```

| Option | Meaning |
| --- | --- |
| `--map` | JSON map from source ODF to Redux `PrjID`, or to `{"odf", "prototype"}`. `prototype` names the template record that supplies Redux class data. |
| `--team-map JSON` | JSON map from BZCC team numbers to Redux team numbers. Required when an emitted object or AOI uses a team outside Redux's 0–15 range. |
| `--terrain` | Override the output `TerrainName`. |
| `--mission` | Redux mission class, for example `LuaMission`. |
| `--offset X Y Z` | Add a world offset to every object position and path point. |
| `--offset-from PORT_JSON` | Read that offset from the WorldBuilder terrain report (`object_offset_m`). |
| `--report` | Write a JSON report of counts, substitutions, skips and the offset applied. |
| `--allow-skips` | Write a partial map when objects lack a prototype (listed in the report). |
| `--source-odfs DIR` | BZ2/BZCC ODF folder for the class check. Repeatable, searched recursively; the first match wins. |
| `--redux-odfs DIR` | Redux ODF folder, mod before stock. Repeatable. Turns the class check on. |
| `--auto-map` | Pick a class-compatible template prototype for ODFs not in `--map`. |
| `--allow-approximate` | Let `--auto-map` use approximate classes (see below). |
| `--allow-unsafe-classes` | Write the map even when the class check fails. |

Matching is case insensitive. Redux BZN IDs are limited to eight bytes, so
longer source names need a short `odf` in the map (`bocryst01` becomes
`bocryst0`). See `docs/examples/isdf01_mapping.json`.

### Terrain offset

BZ2/BZCC maps are centred on the origin; Redux terrain starts at its TRN
`MinX`/`MinZ` and cannot hold negative heights. The WorldBuilder terrain port
therefore moves the source raster (for a centred 4096 m BZCC map re-homed to
`0,0`: +2560 m on X and Z) and raises heights by a vertical offset. Objects
must move by the same amount or they end up off the map. Always pass
`--offset-from` with the terrain report from the same terrain build.

### Team numbers

Redux teams are 0–15. The converter preserves valid source team numbers, but
stops if an emitted object or AOI has a team outside that range. It does not
guess faction relationships from BZCC team IDs. Supply an explicit map, for
example ISDF01's player, allied scouts and enemy turret:

```json
{"17": 1, "16": 3, "34": 2}
```

The map applies to both objects and AOIs. The conversion report lists the
source-to-target changes actually used in `applied_team_map`. Check the target
mission script's team assumptions when choosing the values; ISDF01's Lua uses
team 1 for the player, 3 for initial allies, and 2 for enemies.

## Class check

BZCC and Redux ODFs both carry a `classLabel`, but they do not mean the same
thing:

- A BZCC `classLabel` is either an engine class (`wingman`) or the name of
  another ODF to inherit from (`ivscout`). Redux accepts only engine classes and
  has no ODF-to-ODF inheritance.
- A BZN object record depends on its class. A craft has cloak fields and a
  turret tank has turret fields. The ported object must therefore be cloned
  from a Redux prototype with a matching record, or Redux reads the wrong
  fields.

`class_labels.py` checks both. Pass `--redux-odfs` to `bzcc_port.py` to run it
before the port, or run it on its own for a report:

```text
python class_labels.py source.bzn --source-odfs BZ2R/bz2r_res     --redux-odfs "addon/My Mod" --redux-odfs StockODFFiles     --template redux_template.bzn --map odf_map.json --json classes.json
```

For every source ODF it:

1. follows the BZCC `classLabel` chain to an engine class
   (`ivplysct -> ivscout -> wingman`), noting any inheritance the Redux ODF
   must now carry itself;
2. maps that class to Redux with a safety tier;
3. checks the Redux ODF of the same name (after `--map` renames) has a valid
   Redux `classLabel` that agrees with the source class;
4. checks the chosen prototype has a compatible BZN record, and with
   `--auto-map` picks one.

| Tier | Meaning | Automatic |
| --- | --- | --- |
| `exact` | Same engine class and role (`wingman`, `i76building`, `turrettank`, `ammopack`...). | Yes |
| `approximate` | No Redux class; the suggestion keeps placement but loses behaviour: `terrain`/`plant`/`extractor` become `i76building`, `deposit` becomes `geyser`, `morphtank` becomes `wingman`. | With `--allow-approximate` |
| `role-changed` | Same name, different role: BZCC `recycler`, `factory` and `armory` are buildings, while Redux's are deployable craft. | Never |
| `unsupported` | No Redux equivalent (`pointlight`, `spotlight`, `objectspawn`, `animal`...). | Never; the object is skipped |

Prototype compatibility is strict, with one exception. Some classes store only
the base GameObject fields in a mission BZN, so a prototype of one can place
any other:

- buildings: `i76building`, `i76building2`, `i76sign`, `artifact`, `barracks`,
  `commtower`, `geyser`, `powerplant`, `repairdepot`, `scrap`, `scrapfield`,
  `spawnpnt` and `supplydepot`;
- powerups: `ammopack`, `repairkit`, `wpnpower`, `camerapod` and `daywrecker`.

The evidence: Redux `Building::Save` and `PowerUp::Save` add nothing in
mission saves, and in the named BZ1 1.5 decompile none of those subclasses
overrides `Save`. Mines, scrap silos, craft and turrets do add fields, so they
need a prototype of the same class.

A status other than `ok` means one of two things:

- **The port fails.** A bad record or ODF would reach Redux:
  `prototype-mismatch`, `unknown-prototype`, `invalid-redux-label`,
  `label-mismatch`, `missing-redux-odf` or `id-too-long`.
- **The object is skipped** (`role-changed`, `unsupported`, `approximate`,
  `no-prototype`). Strict mode then stops unless you pass `--allow-skips`.

The report's `class_labels` section lists every diff, problem and note.

`--write-odfs DIR` (on `class_labels.py`) writes copies of source ODFs with
only the `classLabel` value changed. It does this only for automatic tiers and
only for ODFs that do not inherit. Inherited ODFs must still be flattened by
hand.

Where the class lists come from:

- **Redux:** the classes used by the 796 stock Redux ODFs, plus `bullet` and
  `i76building2`, which the Redux executable registers beside `i76building`.
- **BZCC:** the non-ODF `classLabel` values in the BZCC 2.0 `bz2r_res` ODFs.

### ISDF01 findings

All 45 ISDF01 ODFs pass. `ibcrat00` stays an `artifact` and `peclif02`/`03`
stay `i76building2` (an `i76building` with no radar blip); both share their
prototype's record layout.

## Tunnels

BZCC tunnels (for example Pluto `pbatun01`-`06`, and the gates in `pbfenc01`
and `pbfenc02`) are plain `i76building`s. `[BuildingClass] tunnelCount` and
`tunnelNNX0/Z0/DX/DZ/Edge` carve drivable lanes out of the building's pathing
footprint, and BZCC lets you drive both over and through them. The Redux
executable has none of these keys, so a straight port is a solid block to units
and to AI pathing. The class check notes every ODF with a `tunnelCount`.

### What Redux can do instead (engine research)

Sources: named BZ1 1.5 decompile, the Redux decompile and exe (same code and
tables), and BZ98RBlenderToolKit `docs/GEO_TYPES_RESEARCH.md` section 5.1.

- **AI pathing** is a 2D cell grid. At load, entities of class STRUCTURE (2/10)
  and turrets stamp their bounding box as material 5, which is blocked.
  - `i76sign` (class 5) stamps only a perimeter ring of material 4. That costs
    10, like a steep slope, but is still routable.
  - Proximity mines, geysers, scrap fields and spawn points never stamp.
  - The only terrain that blocks is geometric cliffs (an adjacent height step
    over the cliff threshold). No entity can make a cell passable again.
- **Drivable decks.** When a model's SDF root part is GEO class 8 (BRIDGE),
  every upward-facing collision polygon (normal y > 0.4) becomes hover floor.
  GEO class 9 (FLOOR) opts in single parts.
- **Two levels work.** `Floor_GetFloor` starts from the terrain height and
  accepts a deck only when the deck is below the vehicle + 1 m. So a vehicle
  under a roof drives on the terrain, and a vehicle on top rides the roof.
  `PointOnFloor` returns the first matching polygon per entity, so the roof
  deck and any floor inside the tunnel must not belong to the same object.

### Proposed conversion (needs an in-game test)

1. **Terrain (WorldBuilder).** Dig the tunnel lane into the heightmap down to
   the tunnel floor, with ramps at the portals. The trench walls become cliff
   cells, which keeps AI inside the lane.
2. **Tunnel model.** Use an `i76sign` ODF so the footprint stays routable. Its
   SDF root is BRIDGE (8), and it has roof and wall collision but no interior
   floor faces, because the dug terrain is the floor. The roof top becomes the
   surface you drive over.
3. **Known gap.** The path grid has one level. Surface AI sees the trench walls
   as cliffs and routes around the tunnel instead of over it. Fixing that needs
   a post-load `cellType` stamp (a shim or loader patch).

The current workaround is isdfms15's: cap the portals with plates and "tunnel
closed" signs.

## Tests

```text
python -m unittest -v tests.test_bzcc_port tests.test_class_labels
```

## Scope and limits

- Object class state comes from the selected Redux prototypes. Mission Lua is
  a separate file; the utility does not translate BZCC DLL logic.
- A BZN alone is not a complete map. Redux still needs compatible terrain and
  assets, including the `.trn`, `.hg2`, `.mat` and referenced ODF/model files.
- Binary source parsing follows the [BZNTools](https://github.com/GrizzlyOne95/BZNTools) reference BZ2 token layout. Because binary
  records have no object end markers, it recognizes the next object by its
  header signature. Unusual or malformed files may require an ASCII export.
- Source extraction was checked against 37 installed BZ2 maps and 58 installed
  BZCC maps. ISDF01 was ported end to end: 126 objects and 70 paths (192
  points). After the terrain offset, 90% of objects sit within 2 m of the
  ported ground (median error 0.1 m); the rest are cliff props that BZCC sinks
  into the terrain.
- ISDF01's source BZN already names its five-point boundary `edge_path`.
  Redux accepts only two or four boundary points. The fifth ISDF01 point nearly
  repeats the first, so the converter removes that closing point and retains
  four corners. Other unsupported counts fail with an explicit error. It
  applies the terrain offset to the retained points. With the WorldBuilder
  `0,0` terrain origin, the converted boundary bounds are
  X 2064.19–4599.41 m and Z 518.15–3226.96 m, within the 5120 m Redux
  terrain. The port report records source and output point counts and bounds.

## TODO

- **Inheritance flattening.** Merge the keys of a BZCC parent ODF into its
  child when writing Redux ODFs; today inherited ODFs are only reported.
- **More record evidence.** Confirm the remaining Building/PowerUp subclasses
  (`AnimBuilding`, `ShieldTower`, `SprayBuilding`) and their labels.
- **Tunnel conversion.** Test the bridge-deck tunnel in game; then add
  footprint export here and trench carving to WorldBuilder (see Tunnels).
- **GUI.** Expose the port and class check in `toolbox_app.py` next to the scan modes.
