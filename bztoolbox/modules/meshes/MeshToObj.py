#!/usr/bin/env python3
"""
Ogre Mesh to OBJ Converter
Converts Ogre .mesh files to OBJ format via XML intermediate
(the binary reader is built in; no Ogre command-line tools are needed)
"""

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
import argparse

from battlezone.meshes.ogre import MeshError, mesh_to_xml_file


def obj_output_name(source_name):
    lower_name = source_name.lower()
    if lower_name.endswith(".mesh.xml"):
        return source_name[:-9] + ".obj"
    if lower_name.endswith(".mesh"):
        return source_name[:-5] + ".obj"
    if lower_name.endswith(".xml"):
        return source_name[:-4] + ".obj"
    return source_name + ".obj"

class OgreXMLConverter:
    """Binary .mesh -> .mesh.xml, in pure Python (battlezone.meshes.ogre).

    Replaces the OgreXMLConverter executable, so conversion works on every
    platform. The XML layout matches what OgreXMLConverter wrote.
    """

    def __init__(self, ogre_tools_path=None):
        # ogre_tools_path is accepted for compatibility; no external tool is used
        self.converter = "built-in"

    def convert_to_xml(self, input_file, output_dir=None):
        """Convert a single .mesh file to XML; returns the XML path or None."""
        input_path = Path(input_file)
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            output_path = Path(output_dir) / input_path.name
        else:
            output_path = input_path
        xml_output = str(output_path) + '.xml'
        try:
            mesh_to_xml_file(input_path, xml_output)
        except (OSError, MeshError) as e:
            print(f"✗ Failed to convert {input_path.name}: {e}")
            return None
        print(f"✓ Converted {input_path.name} to XML")
        return xml_output

    def batch_convert(self, input_dir, output_dir=None, extensions=(".mesh",)):
        """Convert all Ogre files in a directory"""
        input_path = Path(input_dir)
        converted_files = []

        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)

        for ext in extensions:
            for file in input_path.rglob(f'*{ext}'):
                xml_output_dir = None
                if output_dir:
                    rel_parent = file.parent.relative_to(input_path)
                    xml_output_dir = Path(output_dir) / rel_parent
                xml_file = self.convert_to_xml(file, xml_output_dir)
                if xml_file:
                    converted_files.append(xml_file)

        return converted_files


class OgreXMLToOBJ:
    """Converts Ogre XML mesh files to OBJ format"""
    
    def __init__(self):
        self.vertices = []    # list[(x,y,z)]
        self.normals = []     # list[(nx,ny,nz)]
        self.uvs = []         # list[(u,v)]
        self.submeshes = []   # list[{material, faces, index}]
        
    def parse_mesh_xml(self, xml_file):
        """Parse Ogre mesh XML file"""
        tree = ET.parse(xml_file)
        root = tree.getroot()
        
        # Parse shared geometry if exists
        shared_geom = root.find('sharedgeometry')
        if shared_geom is not None:
            self._parse_geometry(shared_geom, is_shared=True)
        
        # Parse submeshes
        submeshes = root.find('submeshes')
        if submeshes is not None:
            for idx, submesh in enumerate(submeshes.findall('submesh')):
                self._parse_submesh(submesh, idx)
    
    def _parse_geometry(self, geom_elem, is_shared=False, offset=0):
        """
        Parse geometry section (vertices, normals, UVs).
        Handles multiple <vertexbuffer> elements by merging them per vertex index.
        """
        # Try to get vertex count from this element
        vcount_attr = geom_elem.get('vertexcount')
        if vcount_attr is not None:
            vertex_count = int(vcount_attr)
        else:
            # Fallback: count vertices in the first vertexbuffer
            first_vb = geom_elem.find('vertexbuffer')
            if first_vb is not None:
                vertex_count = len(first_vb.findall('vertex'))
            else:
                return 0
        
        # Per-vertex data containers
        local_verts = [None] * vertex_count
        local_normals = [None] * vertex_count
        local_uvs = [None] * vertex_count
        
        any_normals = False
        any_uvs = False
        
        # Merge data from all vertexbuffers
        for vb in geom_elem.findall('vertexbuffer'):
            has_positions = vb.get('positions', 'false').lower() == 'true'
            has_normals = vb.get('normals', 'false').lower() == 'true'
            tex_coords = int(vb.get('texture_coords', '0') or 0)
            has_texcoords = tex_coords > 0
            
            for i, vertex in enumerate(vb.findall('vertex')):
                if i >= vertex_count:
                    break  # Safety
                
                # Position
                if has_positions:
                    pos = vertex.find('position')
                    if pos is not None:
                        x = float(pos.get('x', 0))
                        y = float(pos.get('y', 0))
                        z = float(pos.get('z', 0))
                        local_verts[i] = (x, y, z)
                
                # Normal
                if has_normals:
                    normal = vertex.find('normal')
                    if normal is not None:
                        nx = float(normal.get('x', 0))
                        ny = float(normal.get('y', 0))
                        nz = float(normal.get('z', 0))
                        local_normals[i] = (nx, ny, nz)
                        any_normals = True
                
                # UVs (first texcoord set)
                if has_texcoords:
                    texcoord = vertex.find('texcoord')
                    if texcoord is None:
                        # Some exporters might use texcoord0, texcoord1, etc.
                        for child in vertex:
                            if child.tag.startswith('texcoord'):
                                texcoord = child
                                break
                    if texcoord is not None:
                        u = float(texcoord.get('u', 0))
                        v = float(texcoord.get('v', 0))
                        # Flip V for OBJ (OpenGL-style to OBJ-style)
                        local_uvs[i] = (u, 1.0 - v)
                        any_uvs = True
        
        # Fill in any missing data with safe defaults
        for i in range(vertex_count):
            if local_verts[i] is None:
                local_verts[i] = (0.0, 0.0, 0.0)
        
        if any_normals:
            for i in range(vertex_count):
                if local_normals[i] is None:
                    local_normals[i] = (0.0, 1.0, 0.0)
        else:
            local_normals = []
        
        if any_uvs:
            for i in range(vertex_count):
                if local_uvs[i] is None:
                    local_uvs[i] = (0.0, 0.0)
        else:
            local_uvs = []
        
        # Append to global arrays
        self.vertices.extend(local_verts)
        if any_normals:
            self.normals.extend(local_normals)
        if any_uvs:
            self.uvs.extend(local_uvs)
        
        return vertex_count
    
    def _parse_submesh(self, submesh_elem, submesh_idx):
        """Parse a submesh"""
        material = submesh_elem.get('material', f'material_{submesh_idx}')
        uses_shared = submesh_elem.get('usesharedvertices', 'false').lower() == 'true'
        
        vertex_offset = len(self.vertices)
        
        # Parse local geometry if not using shared
        if not uses_shared:
            geom = submesh_elem.find('geometry')
            if geom is not None:
                vertex_offset = len(self.vertices)
                self._parse_geometry(geom, is_shared=False, offset=vertex_offset)
        else:
            # Shared geometry starts at the beginning of global vertex list
            vertex_offset = 0
        
        # Parse faces (indices)
        faces_elem = submesh_elem.find('faces')
        local_faces = []
        if faces_elem is not None:
            for face in faces_elem.findall('face'):
                v1 = int(face.get('v1')) + vertex_offset + 1  # OBJ is 1-indexed
                v2 = int(face.get('v2')) + vertex_offset + 1
                v3 = int(face.get('v3')) + vertex_offset + 1
                local_faces.append((v1, v2, v3))
        
        self.submeshes.append({
            'material': material,
            'faces': local_faces,
            'index': submesh_idx,
        })
    
    def write_obj(self, output_file, mtl_file=None):
        """Write OBJ file"""
        out_path = Path(output_file)
        base_name = out_path.stem
        
        total_faces = sum(len(sm['faces']) for sm in self.submeshes)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("# Converted from Ogre mesh format\n")
            f.write(f"# Vertices: {len(self.vertices)}\n")
            f.write(f"# Faces: {total_faces}\n\n")
            
            if mtl_file:
                f.write(f"mtllib {Path(mtl_file).name}\n\n")
            
            # Vertices
            for v in self.vertices:
                f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            f.write("\n")
            
            # UVs
            for uv in self.uvs:
                f.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")
            f.write("\n")
            
            # Normals
            for n in self.normals:
                f.write(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n")
            f.write("\n")
            
            have_uvs = len(self.uvs) == len(self.vertices) and len(self.uvs) > 0
            have_normals = len(self.normals) == len(self.vertices) and len(self.normals) > 0
            
            # Faces by submesh as separate OBJ objects
            for idx, submesh in enumerate(self.submeshes):
                obj_name = f"{base_name}_part{idx}"
                f.write(f"# Submesh - {submesh['material']}\n")
                f.write(f"o {obj_name}\n")
                f.write(f"g {submesh['material']}\n")
                if mtl_file:
                    f.write(f"usemtl {submesh['material']}\n")
                
                for face in submesh['faces']:
                    if have_uvs and have_normals:
                        f.write(
                            f"f {face[0]}/{face[0]}/{face[0]} "
                            f"{face[1]}/{face[1]}/{face[1]} "
                            f"{face[2]}/{face[2]}/{face[2]}\n"
                        )
                    elif have_uvs:
                        f.write(
                            f"f {face[0]}/{face[0]} "
                            f"{face[1]}/{face[1]} "
                            f"{face[2]}/{face[2]}\n"
                        )
                    elif have_normals:
                        f.write(
                            f"f {face[0]}//{face[0]} "
                            f"{face[1]}//{face[1]} "
                            f"{face[2]}//{face[2]}\n"
                        )
                    else:
                        f.write(f"f {face[0]} {face[1]} {face[2]}\n")
                f.write("\n")
    
    def write_mtl(self, output_file, texture_search_roots=None):
        """Write MTL file and auto-wire textures by recursively searching all subfolders.

        Searches for textures matching base OBJ name with suffixes:
          _d (diffuse), _e (emissive), _n (normal), _s (specular)
        Example: cvapc_d.tga, cvapc_e.tga, cvapc_n.tga, cvapc_s.tga
        """

        out_path = Path(output_file)
        base_name = out_path.stem  # e.g. 'cvapc'
        root_dirs = []
        for root in texture_search_roots or [Path.cwd()]:
            root_path = Path(root)
            root_dirs.append(root_path.parent if root_path.is_file() else root_path)

        # Suffix → MTL map type
        suffix_to_map = {
            "_d": "map_Kd",    # diffuse
            "_e": "map_Ke",    # emissive
            "_n": "map_Bump",  # normal
            "_s": "map_Ks",    # specular
        }

        exts = [".tga", ".png", ".jpg", ".jpeg", ".dds", ".tif", ".tiff", ".bmp"]

        # Recursive search for textures
        def find_tex(suffix: str):
            for root_dir in root_dirs:
                if not root_dir.exists():
                    continue
                for ext in exts:
                    for path in root_dir.rglob(f"{base_name}{suffix}{ext}"):
                        return os.path.relpath(path, out_path.parent)
            return None

        found_textures = {suffix: find_tex(suffix) for suffix in suffix_to_map.keys()}

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("# Material library for Ogre mesh\n\n")
            for submesh in self.submeshes:
                mat_name = submesh["material"]
                f.write(f"newmtl {mat_name}\n")
                f.write("Ka 1.0 1.0 1.0\n")
                f.write("Kd 0.8 0.8 0.8\n")
                f.write("Ks 0.5 0.5 0.5\n")
                f.write("Ns 32.0\n")
                f.write("d 1.0\n")
                f.write("illum 2\n")

                # Attach textures we found
                for suffix, map_key in suffix_to_map.items():
                    tex = found_textures.get(suffix)
                    if tex:
                        f.write(f"{map_key} {tex}\n")

                f.write("\n")

    
    def convert(self, xml_file, obj_file, create_mtl=True, texture_search_roots=None):
        """Main conversion method"""
        self.parse_mesh_xml(xml_file)
        
        mtl_file = None
        if create_mtl and self.submeshes:
            mtl_file = Path(obj_file).with_suffix('.mtl')
            self.write_mtl(mtl_file, texture_search_roots=texture_search_roots)
        
        self.write_obj(obj_file, mtl_file)
        print(f"✓ Converted {Path(xml_file).name} to {Path(obj_file).name}")


def main():
    parser = argparse.ArgumentParser(
        description='Convert Ogre mesh files to OBJ format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert single mesh file
  python MeshToObj.py mesh.mesh -o output.obj
  
  # Batch convert all meshes in directory
  python MeshToObj.py --batch input_dir/ -o output_dir/
  
        """
    )
    
    parser.add_argument('input', help='Input .mesh/.xml file or directory (with --batch)')
    parser.add_argument('-o', '--output', required=True, help='Output .obj file or directory')
    parser.add_argument('--batch', action='store_true', help='Batch process directory')
    parser.add_argument('--ogre-tools', help=argparse.SUPPRESS)  # accepted, no longer needed
    parser.add_argument('--keep-xml', action='store_true', help='Keep intermediate XML files')
    parser.add_argument('--no-mtl', action='store_true', help='Do not create MTL file')
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    had_errors = False

    if args.batch and not input_path.is_dir():
        print("✗ Batch mode requires an input directory")
        return 1
    if not args.batch and input_path.is_dir():
        print("✗ Single-file mode requires an input file")
        return 1

    # Initialize converter
    xml_converter = OgreXMLConverter(args.ogre_tools)
    
    if args.batch:
        import shutil

        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        xml_dir = output_dir / 'xml_temp'
        xml_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n=== Converting Ogre files to XML ===")
        xml_files = xml_converter.batch_convert(args.input, xml_dir)
        print(f"XML conversion returned {len(xml_files)} files")
        
        actual_xml_files = list(xml_dir.rglob('*.xml'))
        print(f"Actually found {len(actual_xml_files)} XML files in {xml_dir}")
        for xf in actual_xml_files:
            print(f"  - {xf.relative_to(xml_dir)}")
        
        if not xml_files and actual_xml_files:
            print("Using files found by scanning directory...")
            xml_files = [str(f) for f in actual_xml_files]
        
        if not xml_files:
            print("✗ No XML files were produced from the input directory")
            return 1

        print(f"\n=== Converting XML to OBJ ===")
        print(f"Processing {len(xml_files)} XML files")
        
        for xml_file in xml_files:
            xml_path = Path(xml_file)
            print(f"Processing: {xml_path.relative_to(xml_dir)}")
            
            if xml_path.suffix == '.xml':
                rel_xml = xml_path.relative_to(xml_dir)
                obj_rel = rel_xml.with_name(obj_output_name(rel_xml.name))
                obj_file = output_dir / obj_rel
                obj_file.parent.mkdir(parents=True, exist_ok=True)
                
                try:
                    converter = OgreXMLToOBJ()
                    converter.convert(
                        xml_file,
                        obj_file,
                        create_mtl=not args.no_mtl,
                        texture_search_roots=[args.input],
                    )
                except Exception as e:
                    had_errors = True
                    print(f"✗ Error converting {rel_xml}: {e}")
        
        if not args.keep_xml:
            shutil.rmtree(xml_dir)
            print(f"\n✓ Cleaned up temporary XML files")
    else:
        print(f"\n=== Converting to XML ===")
        
        output_path = Path(args.output)
        if output_path.is_dir() or args.output.endswith('/') or args.output.endswith('\\'):
            output_path.mkdir(parents=True, exist_ok=True)
            input_path = Path(args.input)
            target_obj = output_path / obj_output_name(input_path.name)
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            target_obj = output_path
            
        cleanup_xml = False
        if args.input.lower().endswith('.xml'):
            xml_file = args.input
        else:
            xml_file = xml_converter.convert_to_xml(args.input)
            cleanup_xml = True
        
        if xml_file:
            print(f"\n=== Converting XML to OBJ ===")
            print(f"XML file: {xml_file}")
            
            try:
                converter = OgreXMLToOBJ()
                converter.convert(
                    xml_file,
                    target_obj,
                    create_mtl=not args.no_mtl,
                    texture_search_roots=[Path(args.input).parent],
                )
            except Exception as e:
                had_errors = True
                print(f"✗ Error during conversion: {e}")
                import traceback
                traceback.print_exc()
            
            if cleanup_xml and not args.keep_xml and os.path.exists(xml_file):
                os.remove(xml_file)
                print(f"✓ Cleaned up temporary XML file")
        else:
            print("✗ Failed to create XML file")
            return 1
    
    print("\n✓ Conversion complete!")
    return 1 if had_errors else 0


if __name__ == '__main__':
    sys.exit(main())
