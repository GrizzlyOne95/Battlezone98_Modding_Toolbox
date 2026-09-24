# Licensing

The toolbox is a combination of components under different licenses. The
component boundaries are kept explicit in the source tree so each one can be
built, replaced or left out on its own.

| Component | Path | License |
| --- | --- | --- |
| Toolbox shell, shared core, and every module not listed below | `bztoolbox/`, `battlezone/` | MIT ([LICENSE](LICENSE)) |
| ZFS archive module and LZO bridge | `bztoolbox/modules/zfs/` (incl. `native/`) | GPL-2.0 ([bztoolbox/modules/zfs/LICENSE](bztoolbox/modules/zfs/LICENSE)) |
| Blender-side Ogre importer | `bztoolbox/modules/meshes/blender/OgreImport.py` | GPL-2.0-or-later (file header) |
| Ogre command-line helpers | `bztoolbox/modules/meshes/bin/` | OGRE project license (MIT) |

## Why the ZFS module is separate

ZFS Specialist was GPL-2.0 because its compressed-archive support links the
GPL LZO library (`native/lzo_bridge.dll`, built from `native/bridge.cpp`).
Consolidation keeps that code inside `bztoolbox/modules/zfs/` and nothing
else imports it: the shell only reaches it through the page registry.

* The **full** Windows build includes the ZFS module. Because the
  distributed program then contains GPL-2.0 code, that build as a whole must
  be distributed under GPL-2.0 terms (the MIT-licensed parts are
  GPL-compatible and stay MIT when taken on their own).
* The **MIT-only** build (`BZTOOLBOX_EXCLUDE_GPL=1`, see
  `packaging/bztoolbox.spec`) leaves the module and the DLL out entirely; the
  Archives page simply does not appear.

CI produces both variants. Replacing LZO with a permissively licensed
decompressor would let the ZFS module move under MIT as well.

## Blender script

`OgreImport.py` runs inside Blender (`blender -b -P ...`) as a separate
program; the toolbox only launches Blender with it. It keeps its original
GPL-2.0-or-later header.

## Third-party assets

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
