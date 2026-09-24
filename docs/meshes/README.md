# Battlezone Mesh Tools

Battlezone Mesh Tools is a Windows GUI utility for fixing and converting Ogre `.mesh` / `.xml` files. It wraps the core Ogre tools with a Battlezone-inspired interface and a clean, single-button workflow.

## Release Builds

Download the latest Windows archive from the GitHub Releases page. The public executable name is intentionally stable and versionless:

- Windows: `BZMeshTools.exe`

Release archives carry the version and platform, for example `Battlezone98Redux_OgreMeshTools-v1.2.3-windows.zip`.

Official Windows builds use the shared **Battlezone Modding Tools** product identity:

```text
FileDescription: Battlezone Mesh Tools
ProductName: Battlezone Modding Tools
CompanyName: GrizzlyOne95
OriginalFilename: BZMeshTools.exe
```

`FileVersion` and `ProductVersion` are derived from the release tag. Non-release CI builds use neutral `0.0.0` metadata.

The bundled Ogre helper executables (`OgreXMLConverter.exe`, `OgreMeshUpgrader.exe`, and `OgreMeshMagick.exe`) retain their upstream/runtime filenames because the conversion workflow invokes them directly.

<img width="1202" height="882" alt="image" src="https://github.com/user-attachments/assets/cadf27b5-c11c-4783-b77b-cea2ec3b3307" />

## What It Can Do

- Recalculate normals to fix bad lighting on legacy meshes.
- Convert Ogre meshes to OBJ (static mesh export).
- Convert Ogre meshes to glTF (`.glb`) using Blender (supports rigs/animations).
- Process a single file or recursively batch-convert entire folders.
- Preserve relative subfolders during batch export.
- Write outputs into `OBJ_Export` and `glTF_Export` directories next to your input unless you choose another output folder.

## How To Use

1. Launch `ogre_mesh_tools_gui.py` (or `BZMeshTools.exe` from the Windows release archive).
2. Choose a single `.mesh` or `.xml` file, or enable `BATCH DIRECTORY MODE` and select a folder.
3. Select the operations you want: `RECALCULATE NORMALS`, `CONVERT TO OBJ`, `CONVERT TO glTF`.
4. `RECALCULATE NORMALS` uses XML conversion internally and writes the updated mesh back when the input is binary `.mesh`.
5. `CONVERT TO OBJ` supports single-file `.mesh` or `.xml` input and writes `.obj` plus `.mtl`.
6. `CONVERT TO glTF` requires Blender and single-file mode expects a `.mesh` input.
7. If using glTF, set your Blender path in `SETTINGS`.
8. Click `PROCESS MESHES`.
9. Click `OPEN EXPORT DIRECTORY` to jump to the results.

## Requirements

- Windows for the prebuilt executable.
- Python 3.x if running from source.
- Blender for glTF export (set in the GUI).
- `OgreXMLConverter.exe` bundled with the repo/release.
- `customtkinter`, `pillow`, and `ogre-python` when running from source.

## Command Line

- `py MeshToObj.py input.mesh -o out_dir\`
- `py MeshToObj.py --batch assets\ -o obj_out\`
- `blender -b -P batch_ogre_to_gltf.py -- input.mesh gltf_out\ OgreXMLConverter.exe`

The CLI tools now return nonzero exit codes when conversion fails, so they are safer to script around.

---
Created for the Battlezone 98 Redux Community.
