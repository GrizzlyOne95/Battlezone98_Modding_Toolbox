"""Battlezone terrain file formats, one reader/writer each.

* :mod:`~battlezone.terrain.hg2`       - HG2 height fields (13-bit samples in zones)
* :mod:`~battlezone.terrain.lgt`       - LGT light maps (bordered Redux / legacy)
* :mod:`~battlezone.terrain.mat`       - MAT tile material maps (64x64 per zone)
* :mod:`~battlezone.terrain.trn`       - TRN terrain descriptions (INI-style text)
* :mod:`~battlezone.terrain.palettes`  - the 33 stock ACT palettes

The modules that used to carry their own copies (WorldBuilder, HeightmapGen,
TextureManager, the Workshop checks) now import these.
"""
