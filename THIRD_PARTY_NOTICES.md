# Third-party notices

## BZONE.ttf

- **Author:** ScrapPool
- **Type:** Fan-made typeface inspired by the visual style of Battlezone
- **Provenance:** Provided directly by the author for free use
- **Game asset status:** Not an extracted original Battlezone game font
- **License documentation:** Permission for free use has been communicated by
  the author; an explicit open-source font license is not yet recorded.

The consolidated toolbox ships one shared copy in `bztoolbox/resources/fonts/`;
some migrated modules still carry their own copy beside their code until they
switch to the shared font loader.

## Orbitron-Bold.ttf

Bundled with the Fonts module (`bztoolbox/modules/fonts/`). Orbitron is
distributed under the SIL Open Font License 1.1.

## Battlezone 98 Redux audio assets

`bztoolbox/modules/audio/commbeep.wav` and `unitbeep.wav` are the property of
Rebellion / Activision and are included for non-commercial fan use and modding
of Battlezone 98 Redux. All rights remain with their owners.

## FFmpeg

Not bundled by default. The Audio module runs the FFmpeg executable chosen in
Settings > External Tools, a copy placed in `bztoolbox/resources/bin/`, or the
one on `PATH`. FFmpeg is licensed under the LGPL 2.1+ (or GPL, depending on
the build) - https://ffmpeg.org.

## OGRE

The Ogre command-line tools and DLLs in `bztoolbox/modules/meshes/bin/` come
from the OGRE project (MIT license) - https://www.ogre3d.org.

## LZO

`bztoolbox/modules/zfs/native/lzo_bridge.dll` links the LZO real-time data
compression library by Markus F.X.J. Oberhumer (GPL-2.0). See
[LICENSING.md](LICENSING.md).

## Python libraries

NumPy, SciPy (BSD), Pillow (HPND), imageio (BSD), customtkinter (MIT),
soundfile (BSD), requests (Apache-2.0), keyring (MIT), qrcode (BSD),
deep-translator (Apache-2.0), google-auth (Apache-2.0), tkinterdnd2 (MIT).
