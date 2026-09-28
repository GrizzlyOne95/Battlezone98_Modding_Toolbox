# ODF Explorer

**Assets › ODF Explorer** (and `bztoolbox odf show` / `bztoolbox odf stats`) shows the value the game actually uses for every field of a project's ODFs, where that value comes from, and craft/weapon stat tables built from those values. Code: `battlezone/odf/explorer.py`.

## Where a value comes from

Redux has **no ODF-to-ODF inheritance** (see [ODF_VALIDATION_SCHEMA.md](../missions/ODF_VALIDATION_SCHEMA.md)): `baseName` never loads another ODF and `classLabel` names an engine class, not a parent file. A field's effective value is:

1. **The ODF itself.** A project `name.odf` replaces the stock `name.odf` outright; keys that only the stock copy sets are *not* used (the explorer shows them as "replaced"). Within a section the last occurrence of a key wins, and `NULL` is not stored (the 1.5 `ParameterDB::FileData` parser). A quoted value runs to the closing quote; an unquoted one ends at the first whitespace.
2. **The prototype default.** `classLabel` (read from `[GameObjectClass]`, `[WeaponClass]`, `[OrdnanceClass]` or `[ExplosionClass]`/`[Explosion]`) selects a prototype class. Each class in its chain reads its own section; a missing key keeps the prototype's value. `wingman` reads `[HoverCraftClass]`, `[CraftClass]` and `[GameObjectClass]`; `machinegun` reads `[CannonClass]` and `[WeaponClass]`. Defaults come from the recovered loader schema; where none was recovered the value is shown as unknown.

A key under a section that no class in the chain reads, or that the section's loader does not read, is **unread**: the game ignores it.

The class chains, labels and defaults are `battlezone/validation/data/redux_odf_classes.json`, generated with the other ODF lint data by `scripts/research/build_odf_params.py` from the BZ1_Source loader schema. `i76building2`/`i76sign` (BuildingClass) and `radarlauncher`/`lobber` are added as labels the schema lists without one.

Stock ODFs are read from `bzone.zfs` of a Redux install (Settings › Game folder, else a detected Steam/GOG install; `--game` on the command line). They resolve the weapons, ordnance and explosions a project names but does not define. Without an install only project ODFs are available and those names are listed as unresolved.

When a project contains the same ODF name more than once (backup folders, for example), the explorer uses the copy closest to the project root and lists the others under Problems; which copy the game loads is not determined.

## Stat tables

Craft rows are project ODFs whose class chain includes `CraftClass`; weapon rows are project ODFs of the `WeaponClass` family, joined with their ordnance (`ordName`) and its vehicle-hit explosion (`xplVehicle`). Every value is the effective value: a key the ODF does not set shows the prototype default when one is known and is listed in `defaulted`.

| Craft column | ODF key |
| --- | --- |
| `unitName`, `scrapCost`, `scrapValue`, `pilotCost`, `buildTime`, `maxHealth`, `maxAmmo` | `[GameObjectClass]` keys of the same name (Battlezone has no armor field) |
| `rangeScan` | `[CraftClass] rangeScan` |
| `speedForward`, `speedReverse`, `speedStrafe`, `accelThrust`, `turnRate` | `[HoverCraftClass] velocForward`, `velocReverse`, `velocStrafe`, `accelThrust`, `omegaTurn`; walkers and persons: the `...Run` keys of `[WalkerClass]`/`[PersonClass]` |
| `weapons` | `[GameObjectClass] weaponHardN=weaponNameN`, marked `(stock)` or `(missing)` |

| Weapon column | ODF key |
| --- | --- |
| `wpnName`, `ordName` | `[WeaponClass]` |
| `shotDelay` | `shotDelay` of the weapon's chain (`[CannonClass]`, `[LauncherClass]`, `[DispenserClass]`, ...) |
| `shotsPerSecond` | 1 / `shotDelay` |
| `ammoCost` | `[SpecialItemClass] ammoCost` for special items, else the ordnance's `[OrdnanceClass] ammoCost` |
| `damageBallistic`, `damageConcussion`, `damageFlame`, `damageImpact`, `shotSpeed`, `lifeSpan`, `xplVehicle` | the ordnance's `[OrdnanceClass]` |
| `damageTotal`, `dps` | sum of the four damage values; `damageTotal * shotsPerSecond` (direct hits; Redux salvo keys are not applied) |
| `range` | `shotSpeed * lifeSpan` (straight flight; missiles accelerate, so it is approximate) |
| `splashRadius`, `splashDamage` | the `xplVehicle` explosion's `[ExplosionClass] damageRadius` and the sum of its four damage values |

## Command line

```text
bztoolbox odf show PROJECT NAME [--game DIR] [--no-stock] [--no-defaults]
bztoolbox odf stats PROJECT [--kind craft|weapon] [--csv OUT] [--game DIR] [--no-stock]
```

`show` marks each field: blank = from the ODF, `~` = prototype default, `!` = not read by the game, with the file and line (or prototype) it comes from and any stock value or earlier duplicate it replaces. `stats` prints the tables; with `--csv` it writes `OUT` for one `--kind`, else `OUT-craft.csv` and `OUT-weapon.csv`.
