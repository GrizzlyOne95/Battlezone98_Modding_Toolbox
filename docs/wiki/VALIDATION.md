# Mapping guide validation

This is the maintainer record for the wiki pages in this folder. It is not a tutorial page.

Checked on 23 October 2026 against release **v0.1.29**, commit `b3cfcf5ca24fd44a13dfd4dd3d002bc08cdd8813`. The checked-out source and that release tag matched for the map tools described here.

## Source references

Links are pinned to the checked release.

| Claims | Source |
| --- | --- |
| Sidebar page names and destinations | [registry.py](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/modules/registry.py) |
| Generator controls, seeds, exports | [gui.py](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/modules/terrain_generator/gui.py) |
| Symmetry operations and order of processing | [builder.py](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/modules/terrain_generator/builder.py), [generation pipeline](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/modules/terrain_generator/__init__.py), [stock detail](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/modules/terrain_generator/stock_detail.py), [natural finish](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/modules/terrain_generator/natural_finish.py) |
| World generation, HG2 loading, PNG export, OBJ buttons, painting and mission overlay | [world_builder.py](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/modules/world/world_builder.py) |
| PNG import, size-field wiring and panel labels | [world_builder_core.py](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/modules/world/world_builder_core.py) |
| Stock output file set and dimensions | [stock_map_creator.py](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/modules/world/stock_map_creator.py) |
| Sample spacing, PNG scaling and HG2 layout | [hg2.py](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/battlezone/terrain/hg2.py) |
| OBJ axes, coordinate origin and grid preservation | [terrain_obj.py](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/modules/world/terrain_obj.py) |
| North-up display and terrain/world bounds | [mission_visualizer.py](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/modules/world/mission_visualizer.py) |
| Relight controls, selection and backups | [heightmap_convert.py](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/app/pages/heightmap_convert.py), [relight.py](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/modules/terrain_generator/relight.py) |
| Project validation button | [validation.py](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/blob/v0.1.29/bztoolbox/app/pages/validation.py) |

## Executed workflow checks

The running Tk application used a temporary project and temporary Toolbox settings. File dialogs were supplied temporary paths so the real page callbacks could run unattended. No game or user mod files were changed.

- Stock Map Creator: `symdemo`, Moon, width/depth 2560 m, empty elevation 0, deterministic MAT variants. The page generated TRN, HG2 and MAT. HG2 readback was 512 × 512 samples, 2 × 2 zones, all heights zero.
- Generated **Compartmented Plateau**, 2 × 2 zones, seed 111, all other settings at defaults. Each of **Mirror X**, **Mirror Z**, **2-way rotational** and **4-way** passed exact array comparisons under the requested operation. HG2 disk readback and a repeated generation also matched exactly.
- The generator UI was set to those values with **Mirror X**, its Generate button was invoked, and its **Export HG2...** callback wrote a file matching the independently generated expected heights exactly.
- Loaded the HG2 through **Browse HG2/PNG** and confirmed that the application's internal zone counts became 2 × 2. Exported a 16-bit PNG with legacy mode off; every PNG value was the corresponding HG2 sample multiplied by eight. Imported that PNG through the GUI conversion worker with neutral brightness/contrast, zero smoothing and the loaded zone counts. Every HG2 sample matched the original.
- Invoked **HG2 -> OBJ**, **IMPORT OBJ** and **OBJ -> HG2** through the real application callbacks. The round trip preserved all 512 × 512 height samples.
- Captured the live generator and HG2 Management controls in `images/`. The sidebar was collapsed to fit the available display. These are screenshots of the application, not mockups.

## Limitations found

- **Terraced Labyrinth** failed an exact Mirror X comparison. **Natural Badlands** and **Cratered Divide** failed all four symmetry comparisons at the tested 2 × 2 / seed 111 settings. Their processing pipeline adds detail after the builder's symmetry pass. The guides therefore recommend the verified **Compartmented Plateau** example and describe final-image mirroring for other styles.
- The PNG converter uses `hg2_target_zw` and `hg2_target_zl`. The visible width/depth fields use separate variables, and the size-preset handler updates those display variables only. Browsing an HG2 does set the actual conversion zone counts. The guide uses that path and explicitly warns about the size fields.
- The visualizer's ASCII BZN parser is experimental. It is documented as an inspection aid, without promises of complete mission parsing or authoritative object placement.

The guide does not claim in-game validation, automatic object symmetry or multiplayer balance. Image-editor edits and 3D-editor UI operations were not automated; the Toolbox's import/export paths were exercised.

## Automated regression checks

```powershell
python -m pytest tests/world/test_terrain_obj.py tests/world/test_hg2_codec.py tests/world/test_stock_map_creator.py tests/terrain_generator/test_heightmap_generator.py -q
```

Result: **29 passed, 29 subtests passed**.

```powershell
python -m pytest tests/world/test_mission_visualizer.py tests/world/test_terrain_checks.py tests/terrain_generator/test_lgt.py tests/world/test_mat_codec.py -q
```

Result: **40 passed, 6 subtests passed**. This covers mission-overlay geometry, terrain/lighting checks, relight selection and backups, LGT encoding, and MAT painting.

## Publishing

The GitHub wiki is a separate Git repository, `Battlezone98_Modding_Toolbox.wiki.git`. Copy the five tutorial pages, `_Sidebar.md`, `_Footer.md` and `images/` from here into that repository, then commit and push. Keep this maintainer file in the main repository. Images in the published pages use `raw.githubusercontent.com/wiki/...` URLs.
