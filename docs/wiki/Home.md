# Battlezone 98 Modding Toolbox guides

These guides use the Toolbox **v0.1.29** UI, checked on **23 October 2026**.

## Making a measured or symmetric map

The Toolbox can generate symmetric terrain, set world dimensions in metres, and exchange heightmaps with image and 3D editors. It does **not** have a general object-placement editor with X/Z entry boxes. Terrain symmetry does not place or mirror bases, scrap, spawns, or mission paths.

Start here:

1. [Create the world files](Create-a-world).
2. [Generate symmetric terrain](Symmetric-terrain).
3. [Make measured terrain edits](Measured-terrain): the 5 m grid, 16-bit PNG editing, and OBJ editing.
4. [Check the finished map](Check-your-map).

## Get the Toolbox

Download it from [GitHub Releases](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/releases/latest). For installation and running from source, see the [repository README](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox#readme).

In the application, expand **World & Terrain** in the left sidebar. If the sidebar is hidden, click **☰**.

| Page | Use it for |
| --- | --- |
| **World Builder** | Create world files; convert PNG/OBJ terrain; paint terrain; inspect a mission overlay. |
| **Generate Terrain** | Generate a new heightmap with a seed and symmetry setting. |
| **Heightmap Convert** | Convert legacy HGT ↔ Redux HG2, or rebake lighting. PNG and OBJ controls are inside **World Builder**, under **HG2 Management**. |

The guides describe terrain authoring and checks. They do not replace creating and testing a mission in Battlezone.
