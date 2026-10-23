# Create a world

This creates a flat terrain and its world configuration. You can then replace its heights with generated or edited terrain.

## Create a 2560 × 2560 m world

1. Make an empty folder for the map.
2. Open **World & Terrain → World Builder**.
3. Select the **Stock Map Creator** tab.
4. Set **Map Name** to `symdemo`. Use 1–8 alphanumeric characters.
5. Select a **World / Biome**, such as **Moon**.
6. Under **MakeTRN Compatibility**, enter **Width: 2560** and **Depth: 2560**. These overrides take priority over **Map Size**.
7. Leave **Empty elevation (/e)** at `0` for this example. Leave **Layer file (/p)** empty.
8. Click **GENERATE MAP FILES** and choose your empty folder.
9. Check the log and confirm that the folder contains `symdemo.trn`, `symdemo.hg2`, and `symdemo.mat`.

Use dimensions that are multiples of **1280 m**. Other requested dimensions are normalized to terrain zones; check the actual size reported in the log.

| File | Contains |
| --- | --- |
| `.trn` | World dimensions, terrain textures, lighting and other world settings. |
| `.hg2` | Terrain heights. |
| `.mat` | Terrain texture placement. This is separate from an Ogre `.material` file. |
| `.lgt` | Terrain lighting, when supplied or rebaked. Stock Map Creator does not generate this file. |
| `.bzn` | Mission objects and mission data. Stock Map Creator does not generate this file. |

## Add generated terrain

Follow [Generate symmetric terrain](Symmetric-terrain), using **Zones X: 2** and **Zones Z: 2** to match this world.

Export the generated heightmap as `symdemo.hg2` into the world folder, replacing the flat file. Keep a copy before replacing an existing map's terrain.

The files must agree on size. For this example, the TRN is **2560 × 2560 m** and the HG2 is **2 × 2 zones / 512 × 512 samples**.

Replacing the HG2 changes heights only. Follow [Check your map](Check-your-map) to repaint terrain, rebake lighting and test the mission.

## A world is not a complete mission

You still need a BZN mission that refers to this terrain, along with the appropriate mission and multiplayer setup. Create or adapt that in the game's map/mission workflow. The Toolbox's terrain generator does not create starting bases, teams or multiplayer spawns.

[Home](Home) · [Next: symmetric terrain](Symmetric-terrain)
