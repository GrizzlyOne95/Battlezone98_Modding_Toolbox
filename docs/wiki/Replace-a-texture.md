# Replace one texture

Start with a working model or world and a known diffuse texture that it already uses. This guide converts an edited image to DDS and packages it under the existing texture name.

## Find the right texture

Use **Project → Dependencies** to follow the model's material reference to its texture. Keep a copy of the original. If it is packed in a ZFS archive, [extract it first](Extract-a-stock-asset).

Use an image editor for the artwork. Keep the original dimensions and alpha channel for this first exercise. Save the edited image as PNG in an art folder outside the mod, using the intended basename. For example, `example_d.png` converts to `example_d.dds`.

## Convert it

1. Open **Assets → Textures & Images → Texture Manager**.
2. Under **Single File Source**, click **Browse** and choose the edited PNG.
3. Set **Output Format** to **.dds**.
4. Set **Compression** to **DXT1** for an opaque diffuse texture, or **DXT5** if it needs a smooth alpha channel. **Auto** chooses based on alpha detection.
5. Turn **Gen Mipmaps** on.
6. Set **Rescale if > :** to **Disabled** to preserve the source dimensions.
7. Leave **Create Emissive**, **Create Specular** and **Smart Normal** off for this exercise.
8. Leave **Overwrite Existing** off for the first conversion.
9. Click **Process Single File** and read the log.

**The DDS is written beside the source PNG.** The batch output-folder field does not select the destination for **Process Single File**. If that DDS already exists and overwriting is off, the log reports that it was skipped.

## Put it into the mod

1. Copy the new DDS into the working mod folder, replacing the intended local texture if one exists.
2. Match the filename used by the material. Keep the original basename if this is an existing texture replacement.
3. Run validation, rebuild the dependency graph, and [test in game](Open-and-test-a-mod#launch-a-test).
4. Check the surface nearby and at a distance. For transparent textures, check the edges and alpha too.

This replaces every surface that resolves to that texture name. Giving a unit its own material and texture is a separate workflow.

The verification converted test images to DXT1 and DXT5. A 64 × 64 source with mipmaps produced seven mip levels, down to 1 × 1.

[Home](Home) · [Extract a stock asset](Extract-a-stock-asset)
