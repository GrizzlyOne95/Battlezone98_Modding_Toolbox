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

## BZNParser (BZNTools)

`battlezone/bzn/bz1.py` is a Python port of the Battlezone 1 parts of
BZNParser (the `BZNStreamReader`/`BZNStreamWriter` token layer and the
version-gated `Hydrate`/`Dehydrate` code of `BZNFileBattlezone`,
`EntityDescriptor`, `AiCmdInfo`, `AreaOfInterest`, `AiPath` and the BZ1
`GameObject` classes), and `battlezone/bzn/data/bz1_class_labels.txt` is its
`BZ1_ClassLabels.txt`. MIT License, Copyright (c) 2026 John "Nielk1" Klein:

> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

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
