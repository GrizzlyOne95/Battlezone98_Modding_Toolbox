# Make a playable map

A map the game can load needs four things together: terrain files (TRN, HG2, MAT, LGT), a mission BZN, an INI that puts it in a menu, and a folder in `addon`. The Toolbox writes all of them at once.

## Which menu, which mission class

| Map Type | Shows in | BZN mission class |
| --- | --- | --- |
| `instant_action` | Instant Action | `LuaMission` |
| `multiplayer` | Multiplayer | `MultDMMission` (Deathmatch) or `MultSTMission` (Strategy) |

The INI's **mapType** picks the menu. The BZN's mission class decides whether the map loads from it: an Instant Action class such as `Inst4XMission` does not load from the Multiplayer menu. A multiplayer map also needs at least one spawn point.

## Start a new map

1. On the **Home** page, click **New mod…**.
2. Enter a **Content Name** of 1-8 letters or digits. This is the map's file name.
3. Choose a **Map Type**: `instant_action` or `multiplayer`.
4. Under **STARTER MAP**, choose a **World**, a **Size (km per side)** and a **Layout**.
5. For a multiplayer map, set **Game Type**, **Min Players** and **Max Players**.
6. Click **CREATE CONTENT** and choose a parent folder. The map is written to `<parent>\<name>\` and opens as the project.

An Instant Action map holds only the player's tank. A multiplayer map gets one spawn point per **Max Players**, in a ring facing the centre.

## Save generated terrain as a map

1. Open **Generate Terrain** and make the terrain you want. See [Make a simple arena](Simple-arena) or [Generate symmetric terrain](Symmetric-terrain).
2. Wait until the preview finishes generating.
3. Click **Save as Map...**.
4. Fill in the name, **Map Type**, **World** and multiplayer settings, then click **SAVE MAP** and choose a parent folder.

The map is written to `<parent>\<name>\`. Open it with **Open mod folder…** to test it.

The map keeps the terrain's own size, including non-square terrain. Terrain higher than 409.5 m is refused; lower it first.

## Test it

1. Open the map folder with **Open mod folder…** if it is not already the project.
2. Open **Project → Test in Game** and pick the map's BZN under **Mission**.
3. Keep **Copy the project into addon\** selected; the test modes change only that copy.
4. Set **Test the map as**:
   - **as is**: deploy the project unchanged.
   - **offline**: the map shows in Instant Action. A multiplayer class becomes `LuaMission`.
   - **multiplayer**: the map shows in the Multiplayer menu with a multiplayer class. The game starts at its menu.
5. Click **Launch**.

A test mode changes only the deployed copy in `addon`, never your project.

## Add or move spawn points

A multiplayer map without a spawn point cannot load from the Multiplayer menu, so place spawn points from an offline load:

1. Test the map **offline**.
2. In game, open the map editor and place spawn points.
3. Save the mission over the map's BZN.
4. Copy the saved BZN back into your project folder. The game does not save into your project.

An offline test gives a multiplayer map the `LuaMission` class, so the BZN you save has it too. **Test the map as** multiplayer switches the deployed copy back for each test. The project's BZN keeps `LuaMission`, and **Check map** reports it. The Toolbox cannot change a BZN's class yet: before you publish, edit the class name in an ASCII copy of the BZN, or copy the deployed BZN from a multiplayer test back into the project.

## Check the map

On **Project → Test in Game**, click **Check map**. It checks the project as it is, not a test mode's copy. It reports:

- ✗ errors that stop the map loading: missing terrain, a mission class that does not suit the **mapType**, or a multiplayer map with no spawn point.
- ! warnings worth a look, such as fewer spawn points than **maxPlayers**. A player who joins after the last free spawn point is taken waits for a spawn and never enters the game.

[Home](Home) · [Next: check your map](Check-your-map)
