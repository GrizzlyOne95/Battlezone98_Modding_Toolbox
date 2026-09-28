# Cut-and-cover tunnels

Battlezone terrain is a heightfield: one height per sample, so it cannot
overhang. A tunnel in the stock engine is built the way a cut-and-cover
tunnel is: dig a trench into the terrain, then put a roof over it. The roof
is a building that craft can drive on; the trench floor is the terrain.

The toolbox does the terrain half:

- **World & Terrain › Tunnels** (GUI), or
- `bztoolbox terrain tunnel` (CLI),

both built on `battlezone/terrain/tunnel.py` (`carve_trench`, `shade_rect`,
`shade_polygon`, `shade_path`).

## Coordinates

Metres, x east and z north.

- **Map-relative** (the default): measured from the map's south-west corner.
  HG2 sample (row r, column c) is at `x = 5 c`, `z = 5 r` for Redux's 256
  samples per 1280 m zone. Row 0 is the south edge.
- **World**: what a BZN, the in-game editor and AI paths use. World =
  map-relative + the TRN `[Size]` `MinX`/`MinZ`. Pass `--trn map.trn` (or
  `--origin MINX,MINZ`) and give world coordinates; the CLI subtracts the
  origin. Stock maps often have a non-zero origin (misn05: `MinZ=98560`).

LGT cells use the same south-first grid. A Redux LGT (256 cells per zone)
cell sits on HG2 vertex i; a 1.5 LGT (128 per zone) cell i is centred at
`10 i + 2.5` m, the average of vertices 2i and 2i+1.

## The recipe

1. **Carve the trench.**

   ```text
   bztoolbox terrain tunnel misn05.hg2 --trn misn05.trn \
       --path 1000,100060 1200,100100 1400,100060 --width 20 --depth 12 \
       --ramp 60 --roof-shade 1060,100048,1340,100112
   ```

   - `--path`: the centre line, two or more points.
   - `--width`: the flat floor. Make it wider than the widest craft that
     should fit, plus room to steer (20 m suits tanks).
   - `--depth D` follows the ground along the path (smoothed over one width),
     D metres down; `--floor H` is a level floor at height H. Keep the roof's
     underside above the floor by more than the tallest craft.
   - `--ramp R` adds ramps of R metres at the open ends (`--ramps both|start|
     end|none`). An end without a ramp is closed by a wall.
   - `--wall-slope` is metres down per metre across (default 2, about 63°).
     `0` makes the walls as steep as the 5 m grid allows.
   - Terrain is only ever lowered. Samples that would go below height 0 stop
     there and are reported.

   Without `--out` the `.hg2` and `.lgt` are overwritten after the originals
   are copied to a backup folder (the toolbox data folder, or `--backup`).
   `--dry-run --preview p.png` shows the result without writing.

2. **Relight the trench and shade the roof's footprint.** The light map
   beside the HG2 is rebaked over the carved area with Redux's stock lighting
   (see `bztoolbox terrain relight`) so the walls and floor are lit like the
   rest of the map. Then each `--roof-shade x0,z0,x1,z1` rectangle, or the
   whole trench width along the path with `--shade-path`, is darkened to
   `--shade` (default 64; Redux's own bake never goes below 56) with a soft
   edge of `--feather` metres. Cells already darker keep their value.

   The engine does not shadow terrain under buildings, so without this the
   floor under the roof is as bright as open ground.

3. **Build the roof.** A model placed over the trench with its root part of
   GEO class 8 (BRIDGE): every upward-facing collision polygon becomes hover
   floor, so craft on top ride the roof. GEO class 9 (FLOOR) opts in single
   parts. `Floor_GetFloor` starts from the terrain height and accepts a deck
   only when it is below the vehicle + 1 m, so a craft inside the tunnel drives
   on the terrain floor and a craft on top rides the roof. Give the roof wall
   collision but **no interior floor faces** (the carved terrain is the floor);
   any deck inside the tunnel must be a separate object from the roof, because
   `PointOnFloor` returns only the first matching polygon per object.

   An `i76sign` ODF keeps the footprint routable (it stamps only a perimeter
   ring of cost 4); an `i76building` stamps its whole footprint as blocked.
   See `docs/missions/BZCC_TO_BZR_PORT.md` › *What Redux can do instead*.

4. **Test it in game** (Project › Test in Game): drive through and over,
   check the roof's height clearance, and look at the light at the portals.

## AI routing caveat

The AI path grid has one level. The trench walls are cliff cells (a height
step over the cliff threshold), which keeps AI inside the lane once it is in
the trench, but surface AI sees the walls and routes around the tunnel
instead of over the roof. Nothing in the files can make a cell passable
again; fixing that needs a post-load cell stamp in the engine (a shim or
loader patch). Give AI paths that stay in the trench, or accept that ground
units cross elsewhere. Gentle walls (`--wall-slope 0.5` or less) are not
cliffs but take more width.

## Limits

- The roof shading is a flat value; it does not follow the roof's shape or
  the sun.
- Rebaking replaces any hand-painted light in the carved area.
- Carving along a path that doubles back on itself uses the nearest segment
  for the floor height; keep bends gentle compared with the width.
- The tool edits HG2/LGT only. The MAT (tile materials) is unchanged, so the
  walls show the tiles that were there; repaint with `bztoolbox terrain paint`
  if needed.
