# Make a tougher tank

This exercise changes the stock NSDF tank from **3000** to **4000** health in your mod. It uses a complete copy of `avtank.odf` and keeps the same filename, so it changes that unit type wherever this replacement is active. It does not add a separate build-menu entry.

## Make the edit

1. [Extract `avtank.odf`](Extract-a-stock-asset) into your working mod folder. Keep an untouched copy outside the mod.
2. Open the mod in the Toolbox.
3. Open `avtank.odf` in a text editor.
4. In `[GameObjectClass]`, change the existing health entry:

```ini
maxHealth = 4000
```

5. Save the file. Keep the other entries and sections.

**Replace the existing line; do not add a second `maxHealth` entry.** A project ODF replaces the stock file of the same name completely. It is not a patch containing only the changed fields. `baseName` does not copy another ODF's contents.

## Check the effective value

1. In **Settings → General**, set **Install folder** to your Redux game folder if it has not been detected. This lets the explorer identify stock ODFs.
2. Open **Assets → ODF Explorer** and click **Reload**.
3. Under **Fields**, search for `avtank` and select it.
4. Check that the header identifies it as a stock replacement.
5. Find `[GameObjectClass] → maxHealth`. The value should be **4000**, with your project ODF shown as its source.
6. Open **Stats → Craft** and check the tank's `maxHealth` value there too.
7. Run **Project → Validation**.

**ODF Explorer is an inspector.** Make changes in your text editor, save them, and click **Reload** to inspect the result.

## Test it

[Launch a mission](Open-and-test-a-mod#launch-a-test) that contains an NSDF tank. The deployed project must contain the edited `avtank.odf`. Check the tank's health in game.

To undo the exercise, restore the original working file and redeploy it. If you remove the replacement instead, also remove the stale deployed copy: deployment does not delete destination files.

The Toolbox check confirmed **4000** in both the Fields view and the Craft stats data. Gameplay testing remains your final check.

[Home](Home) · [Prepare a radio line](Prepare-a-radio-line)
