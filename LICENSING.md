# Licensing

Everything in this repository is MIT-licensed ([LICENSE](LICENSE)), and so is
every build: there is one build per platform and it contains no GPL code.

Earlier, two parts were GPL:

| Was | Replaced by |
| --- | --- |
| ZFS Specialist's `lzo_bridge.dll` (links the GPL-2.0 LZO library), which made that tool GPL-2.0 | `battlezone/archives/lzo.py`: an independent pure-Python LZO1X/LZO1Y implementation, written from the bitstream format rather than from the LZO library's code. It is tested against liblzo2 only as a reference, which is not shipped. |
| OgreMeshTools' Blender importer script (GPL-2.0-or-later) | glTF export is gone; `battlezone/meshes/ogre.py` reads Ogre meshes directly. |

The ZFS archive handling in `battlezone/archives/zfs.py` follows ZFS
Specialist's format logic (header detection, directory decryption, the
MakeZFS XOR key). ZFS Specialist and this toolbox have the same author, who
releases that logic, as it appears here, under the MIT license. ZFS Specialist
was GPL-2.0 only because it linked the LZO library, which the toolbox does not
use.

## Third-party components

Bundled fonts and game sounds, and the Python libraries the builds include,
are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
