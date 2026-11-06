# Battlezone 98 Modding Toolbox guides

These guides use the Toolbox UI checked on **23 October 2026**: **v0.1.30** for the starter guides and **v0.1.29** for the mapping guides. The application code is the same in those two releases.

## Start here

Each guide completes one small task. Use a working copy of your mod.

1. [Open a mod and test it](Open-and-test-a-mod): project folder, validation, deployment and logs.
2. [Find and fix a missing asset](Fix-a-missing-asset): follow a reference and check the correction.
3. [Replace one texture](Replace-a-texture): convert to DDS, package it and test it.
4. [Extract a stock asset](Extract-a-stock-asset): find and extract one file from a ZFS archive.
5. [Make a tougher tank](Change-a-unit): edit a complete stock ODF and inspect its health value.
6. [Prepare a radio voice line](Prepare-a-radio-line): process a WAV, export timings and reference it from a unit.
7. [Publish a Workshop item](Publish-a-Workshop-item): private first upload and updates to the same item.

## Make a playable map

[Make a playable map](Make-a-playable-map): start a map or save generated terrain as one, test it offline or in multiplayer, and check its spawn points.

## Making a measured or symmetric map

The Toolbox can generate symmetric terrain, set world dimensions in metres, and exchange heightmaps with image and 3D editors. It does **not** have a general object-placement editor with X/Z entry boxes. Terrain symmetry does not place or mirror bases, scrap, spawns, or mission paths.

Start here:

1. [Create the world files](Create-a-world).
2. [Make a simple arena](Simple-arena): a round arena with plateaus, or open a heightmap you already have.
3. [Generate symmetric terrain](Symmetric-terrain).
4. [Make measured terrain edits](Measured-terrain): the 5 m grid, 16-bit PNG editing, and OBJ editing.
5. [Save it as a playable map](Make-a-playable-map).
6. [Check the finished map](Check-your-map).

## Get the Toolbox

Download it from [GitHub Releases](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/releases/latest). For installation and running from source, see the [repository README](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox#readme).

In the application, use the left sidebar to open the pages named in each guide. If the sidebar is hidden, click **☰**.

| Page | Use it for |
| --- | --- |
| **World Builder** | Create world files; convert PNG/OBJ terrain; paint terrain; inspect a mission overlay. |
| **Generate Terrain** | Generate a new heightmap from a simple layout or a random style, or open an existing HG2 or height image. |
| **Heightmap Convert** | Convert legacy HGT ↔ Redux HG2, or rebake lighting. PNG and OBJ controls are inside **World Builder**, under **HG2 Management**. |

The guides describe terrain authoring and checks. They do not replace creating and testing a mission in Battlezone.
