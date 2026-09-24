Binary meshes written by Ogre 14.6's own `MeshSerializer` (serializer v1.8 and
v1.100, little- and big-endian), used to test the pure-Python reader in
`battlezone/meshes/ogre.py`.

* `basic_*` - two submeshes with local geometry (grid + one triangle).
* `strip_*` - the grid as a triangle strip.
* `colour2uv_*` - adds diffuse colours and a second texture coordinate set.
* `shared_*` - shared geometry split over two vertex buffers, 32-bit indices,
  submesh name table, normals deliberately wrong (0, 0, 0.5).
