# Find and fix a missing asset

Use this when a mission cannot find a unit, weapon, model, texture or sound. Work in a copy of the mod.

## Find the reference

1. [Open the mod folder](Open-and-test-a-mod).
2. Open **Project → Validation** and click **Run validation**. Select the relevant finding and read its location.
3. Open **Project → Dependencies** and click **Build graph**.
4. Open **Not in project**. The **Referenced by** column shows which project file asks for the asset.
5. In **All files**, use **Filter** to find that referring file. Select it and inspect **NEEDS** and **USED BY**.

| Display | Meaning |
| --- | --- |
| Red entry in **Not in project** | The Toolbox classifies the reference as missing. |
| Grey entry | The file is outside the project. It may be stock content; the graph cannot identify every stock model or texture. |
| **Unreferenced** | No project reference was found. This is not proof that the game never loads the file. |

## A small example

The stock tank ODF, `avtank.odf`, contains this entry in `[GameObjectClass]`:

```ini
weaponName1 = "gatstab"
```

If a working copy says `"gatstabb"`, the graph reports `gatstabb.odf` as missing, referenced by `avtank.odf`.

1. Open the working copy of `avtank.odf` in a text editor.
2. Correct `gatstabb` to `gatstab` and save it. Keep the surrounding ODF unchanged.
3. Return to **Dependencies** and click **Build graph** again.
4. Confirm that `gatstabb.odf` has disappeared from the missing list.
5. Run validation again, then [test the mod](Open-and-test-a-mod#launch-a-test).

This exact typo-and-correction exercise was checked through the running Dependencies page.

## If the name is correct

Locate the actual asset. For a stock file, [extract it](Extract-a-stock-asset) only if you need a local copy to inspect or modify. Stock assets do not all need to be bundled with your mod.

For custom content, copy the intended file into the package and include its dependencies. Do not rename an unrelated file just to make the warning disappear.

For textures, follow the reference through the material file. A correctly converted DDS still needs the filename used by that material.

[Home](Home) · [Replace a texture](Replace-a-texture)
