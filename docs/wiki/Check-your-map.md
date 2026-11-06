# Check your map

## After changing heights

1. Back up the working world files.
2. Check that the TRN's width/depth and the HG2's zone counts describe the same world. A 2 × 2 zone HG2 needs a **2560 × 2560 m** TRN.
3. If textures should follow the new slopes and heights, open **World Builder → HG2 Management** and load the **final HG2**. Then open **Auto-Painter**.
4. Click **Load TRN/Rules...** and choose the world's TRN or your layer-rules file. Review the rules and click **Validate**.
5. Click **Generate .MAT...** and save the result for that terrain. Read the result dialog for missing transition textures. The painter replaces texture placement; keep any hand-painted MAT you want to preserve.
6. Open **World & Terrain → Heightmap Convert**. Under **Rebake lighting from HG2**, choose the HG2 with **HG2 or folder**.
7. To force a rebake after an edit, clear **Only light maps that are missing, flat or do not follow the terrain**. Click **Rebake lighting from HG2**. Existing lightmaps are backed up by this tool.

If the TRN has no layer rules, **Load TRN/Rules...** reports that it kept the existing rules. It still loads the texture metadata. Review those rules before painting.

The rebake uses the Toolbox's stock-lighting approximation. Check the result in game, especially if your world uses custom lighting.

## Inspect a mission overlay

1. Open **World Builder → Mission Visualizer**.
2. Click **Load Map Image/HG2** and choose the final HG2.
3. Click **Load .bzn Mission** and choose an **ASCII** BZN for that terrain.
4. Read the information panel. Check **TerrainName**, **MinX / MinZ**, world size and any mismatch warnings.

The visualizer is experimental and read-only. It does not move objects or prove that a map is balanced. Its BZN loader requires ASCII; a binary BZN needs an ASCII copy before it can be used here.

## Run the project checks

Open the mod folder with **Open mod folder…**, then go to **Project → Validation** and click **Run validation**. Review missing assets and malformed terrain/configuration findings.

Validation does not compare the two halves for symmetry or measure travel times.

For a map's menu, mission class and spawn points, click **Check map** on **Project → Test in Game**; see [Make a playable map](Make-a-playable-map#check-the-map).

## Test in Battlezone

Load the mission in the game. Drive both sides and check:

- Base pads, ramps, centre seams and narrow routes.
- Equal resource and spawn placement, including object heights and headings.
- Route lengths and access from both starting positions.
- Terrain textures, lighting and the satellite view.

A symmetric heightmap is a starting point for a balanced map. The mission objects and reachable routes still need checking.

[Home](Home) · [Measured terrain](Measured-terrain)
