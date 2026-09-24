# Third-party notices

## BZONE.ttf

- **Author:** ScrapPool
- **Type:** Fan-made typeface inspired by the visual style of Battlezone
- **Provenance:** Provided directly by the author for free use
- **Game asset status:** Not an extracted original Battlezone game font
- **License documentation:** Permission for free use has been communicated by
  the author; an explicit open-source font license is not yet recorded.

The toolbox ships one copy, `bztoolbox/resources/fonts/BZONE.ttf`, registered
privately for the running process by `bztoolbox/app/fonts.py`.

## Orbitron-Bold.ttf

Bundled with the Fonts module (`bztoolbox/modules/fonts/`). Orbitron is
distributed under the SIL Open Font License 1.1.

## Battlezone 98 Redux audio assets

`bztoolbox/modules/audio/commbeep.wav` and `unitbeep.wav` are the property of
Rebellion / Activision and are included for non-commercial fan use and modding
of Battlezone 98 Redux. All rights remain with their owners.

## Python libraries

NumPy, SciPy (BSD), Pillow (HPND), imageio (BSD), customtkinter (MIT),
soundfile (BSD), requests (Apache-2.0), keyring (MIT), qrcode (BSD),
deep-translator (Apache-2.0), google-auth (Apache-2.0), tkinterdnd2 (MIT).

soundfile's wheels include **libsndfile** (LGPL-2.1+) and its codecs (libogg,
libvorbis, FLAC, opus: BSD; mpg123/LAME for MP3: LGPL). The builds ship that
shared library unmodified, loaded at run time, as the soundfile wheel does;
it can be replaced by another build of libsndfile.
https://libsndfile.github.io/libsndfile/

The optional live mesh preview uses ogre-python (MIT) when it is installed; it
is not needed for any conversion.
