# ODF validation schema

The ODF checker is deliberately **loader-oriented**, not a generic INI linter.

`odf_schema.py` contains curated, evidence-backed Redux loader contracts. `odf_evidence.py` contains structured provenance. `odf_validator.py` evaluates the physical ODF declarations against those contracts. Research/mining output may contain far more discovered sections/keys than the curated validator exposes; that separation is intentional.

## Evidence policy

A hard validator rule should only be added when its behavior is supported strongly enough to justify user-facing diagnostics. Preferred evidence is:

1. Redux executable/decomp loader behavior,
2. code behavior corroborated by stock Redux ODFs,
3. a reproducible runtime failure tied back to the loader path.

Stock-only observations are useful research evidence but should not automatically become hard failures. `inferred`, hash-only, or name-unresolved findings are parse/report research data only until separately verified.

The current schema is intentionally incomplete. Unknown sections and keys are **not** automatically treated as invalid.

## Structured provenance

Schema version 6 uses evidence IDs that resolve into `ODFEvidence` records. An evidence record can carry:

- evidence kind,
- confidence,
- recovered function/symbol,
- executable address,
- related addresses,
- repository/path when actually verified,
- representative stock file,
- runtime reproduction identifier, and
- a concise statement of what the evidence proves.

Confidence vocabulary is deliberately small:

| Confidence | Meaning |
| --- | --- |
| `confirmed-code` | Behavior directly recovered from loader/decomp code. |
| `code+stock` | Code behavior corroborated by stock content or runtime reproduction. |
| `stock-only` | Observed in stock content but not yet code-proven. |
| `inferred` | Hypothesis/research lead; never sufficient by itself for a hard rule. |

Redux executable addresses and BZ1_Source evidence are separate provenance domains. A Redux address must not be labeled as coming from `GrizzlyOne95/BZ1_Source` unless the exact corresponding repository artifact/path has been independently verified.

## Current loader rules

| Rule ID | Context | Redux section | Legacy/problem section | Severity |
| --- | --- | --- | --- | --- |
| `game-object-root` | object root dispatch | `GameObjectClass` | `GameObject` | Error |
| `flare-mine` | `classLabel=flare` + `MineClass` | `FlareMineClass` | `FlareBuildingClass` | Critical |
| `magnet-mine` | `classLabel=magnet` + `OrdnanceClass` + `MineClass` | `MagnetMineClass` | `MagnetClass` | Error |
| `scavenger` | `classLabel=scavenger` + `CraftClass` | `ScavengerClass` | `ScavengerCraftClass` | Error |
| `flame-puff` | `classLabel=flamepuff` + `OrdnanceClass` | `FlamePuffClass` | `flameClass` | Error |
| `explosion-section` | `classLabel=explosion` + `OrdnanceClass` | `ExplosionClass` | `Explosion` | Error |
| `spray-building-section` | `[BuildingClass]` + exact legacy typo | `SprayBuildingClass` | `SprayBuildngClass` | Error |

Context is important. Similar section names can be used in unrelated legacy content, so the validator only applies migration rules when the surrounding loader path is proven.

## Flare crash provenance

`flare-mine` has a concrete recovered failure chain:

1. `FlareMineClass::Load` at `0x004D2B10` resolves `payloadName` into the payload `OrdnanceClass` pointer.
2. `FlareMine::Update(float)` at `0x004D2E90` follows that payload pointer when the mine fires.
3. `OrdnanceClass::Build` at `0x00586FF0` reaches an unguarded dereference when the payload class is null.
4. The confirmed AbsoZero access violation occurs at `0x00586FFC`, reading `+0x38` through a null class pointer.

`[FlareBuildingClass]` has no loader reader in the mined code corpus, so putting `payloadName` there does not initialize the field consumed by the flare firing path. A canonical `[FlareMineClass]` with no `payloadName` is likewise Critical.

The validator deliberately does **not** infer that every flare lacking a physical `[FlareMineClass]` must crash; that stronger absence claim would require direct proof of the relevant prototype/default state.

## `baseName` semantics

A previous validator revision modeled canonical `baseName` as an ODF-to-ODF inheritance edge. Loader mining disproved that model.

Recovered behavior now supports this contract:

- canonical `baseName` has a real code reader,
- that reader does **not** open another `.odf` and merge its sections/keys,
- `baseName` participates in base/prototype selection,
- defaults come from the engine's prototype/class chain,
- missing/empty `baseName` therefore means this field selects no base prototype,
- but absence is **not automatically invalid** for every ODF because root definitions may legitimately have no base prototype.

Therefore the validator does not:

- merge a `baseName` target into the child ODF,
- inherit `classLabel`, sections, or keys from another ODF file,
- treat a missing `baseName` target as a missing-file dependency,
- construct file-level cycles from `baseName`,
- treat duplicate ODF filenames as ambiguous `baseName` parents, or
- suppress a physical missing key because another ODF happens to share the value named in `baseName`.

Lowercase `basename` remains distinct from canonical `baseName`; the validator does not invent global key case-insensitivity.

A future class-specific "missing baseName" diagnostic should only be added when the mined loader/prototype code proves that the class requires a base prototype to function correctly.

## Key spelling and dead-field policy

Key spelling is judged only where code evidence identifies the consumed key. Current examples include:

- `MagnetMineClass.triggerDelay` is code-read; `triggetDelay` has no reader.
- `FlamePuffClass.frameDelay` is code-read; `flameDelay` has no recovered reader despite appearing in stock content.

This is why shipped stock files are corroboration rather than absolute truth: stock data can itself contain dead or stale fields.

## Explosion section contract

The mined explosion path exposes a useful distinction between **dispatch** and **section consumption**. `classLabel = "explosion"` can select the explosion ordnance path while the explosion-specific constructor/loader still reads its configuration from `[ExplosionClass]`.

Therefore an ODF like:

```ini
[OrdnanceClass]
classLabel = "explosion"

[Explosion]
damageRadius = 25
```

is diagnosed because the `[Explosion]` keys are not consumed by the recovered loader. The validator recommends `[ExplosionClass]` only in the proven `classLabel=explosion` + `OrdnanceClass` context; it does not globally rename arbitrary `[Explosion]` sections.

## Spray-building spelling contract

The loader audit also found an exact stock-content typo: four spray-building ODFs use `[SprayBuildngClass]` while recovered code reads `[SprayBuildingClass]`. The misspelled section has no recovered reader, so the fields under it are dead even though the rest of the building ODF can load normally.

The validator intentionally does not guess a class label for this rule. It reports the exact `[SprayBuildngClass]` typo only when the same ODF also contains `[BuildingClass]`; unrelated files that happen to contain the same text are left alone.

## ODF references

The schema currently validates these ODF-valued fields against the combined local + stock filename namespace:

- `FlareMineClass.payloadName`
- `OrdnanceClass.xplGround`
- `OrdnanceClass.xplVehicle`
- `OrdnanceClass.xplBuilding`

Near-miss names receive a suggested replacement, which catches cases such as `xmlasbld` vs `xlasbld`.

Reference checking is a filename/dependency check only. It does not imply `baseName` file inheritance.

## Research corpus boundary

The loader-mining corpus is intentionally broader than the validator. It may contain:

- keyed loaders,
- zero-key chain links,
- hash-only sections,
- name-unresolved keys,
- stock-only anomalies,
- code-proven crash risks,
- guarded conditions that are explicitly safe.

The validator should promote only the subset that has a clear, defensible user-facing consequence. Guarded code paths are recorded specifically to avoid false-positive crash-risk rules.

## Regression corpus

The test suite verifies:

- flare legacy-section and missing-payload crash findings,
- magnet mine section and `triggerDelay` spelling,
- scavenger section naming,
- flame-puff legacy fields and `frameDelay` spelling,
- legacy `GameObject` root dispatch,
- explosion `[Explosion]` vs `[ExplosionClass]` section consumption with a negative control,
- spray-building `SprayBuildngClass` vs `SprayBuildingClass` spelling with canonical and unrelated-file controls,
- ODF reference typo detection,
- ZIP validation without extraction,
- no fabricated `baseName` ODF merging, cycles, missing-parent, or duplicate-parent diagnostics,
- missing `baseName` not being treated as automatically invalid,
- and concrete provenance addresses for the flare crash chain.
