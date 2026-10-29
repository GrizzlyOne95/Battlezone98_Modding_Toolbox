# Make a simple arena

Use this guide when you want a basic map, such as a round arena with a couple of plateaus. You only need the **Basic** controls in **World & Terrain → Generate Terrain**. Leave **Advanced** closed.

First [create the world files](Create-a-world). Note the world's zone counts: a 2560 × 2560 m world is **2 × 2** zones. One zone is 1280 m square.

## Generate a round arena with plateaus

1. Open **World & Terrain → Generate Terrain**.
2. Set **Layout / Style** to **Simple Arena**. The page shows a preview straight away.
3. Set **Zones X** and **Zones Z** to match your world, such as **2** and **2**.
4. Set **Plateaus** to the number you want (0–6). One plateau sits in the centre. Two or more are spaced evenly around the middle of the arena.
5. Move **Plateau height (m)** to set how far the plateau tops rise above the arena floor.
6. Click **GENERATE  (New Terrain)** to try a new random layout. Each click turns the plateau ring to a new angle.
7. Click **Export HG2...**. Save it over your world's HG2, such as `symdemo.hg2`. Keep a copy of the original first.

The plateau tops and the arena floor are flat. A wall rises around the edge of the arena.

The other starting layouts are:

| Layout | Shape |
| --- | --- |
| **Flat Field** | Level ground with gentle rolls. A blank canvas. |
| **Simple Arena** | A round arena, an outer wall and 0–6 flat plateaus. |
| **Two Bases** | Two raised base shelves at opposite ends and a low hill in the centre. |

The styles after these three are random terrain recipes with many more settings.

## Use a heightmap you already have

If you drew your map in an image editor, or already have an HG2, open it instead of generating one.

1. Click **Open HG2 / Height Image...** and choose the file.
2. The file appears in **Layout / Style** as **My file: <name>**. Its preview shows straight away.
3. Use **Terrain Contrast / Vertical Relief** if you want to flatten or steepen it.
4. Click **Export HG2...**.

How the file is read:

| File | Heights |
| --- | --- |
| `.hg2` | Read as-is. Its zone counts are kept. |
| 16-bit greyscale PNG | Lossless. The pixel value is the HG2 height × 8. This is the format of **Export 16-bit Height PNG...**. |
| 8-bit image (PNG, BMP, JPEG, TIFF) | One grey level is 1 m: black is 0 m and white is 255 m. |

An image whose width and height are multiples of 256 pixels keeps its size, at one zone per 256 pixels. Other images are stretched to the **Zones X** and **Zones Z** set before you open them. Set those to match your world first.

## Next

[Check your map](Check-your-map): repaint textures and rebake lighting for the new heights. For a fair two-team map, see [Generate symmetric terrain](Symmetric-terrain).
