#!/usr/bin/env python3
"""
Ogre Mesh XML Normal Recalculation Script
Recalculates vertex normals from face data in Ogre .mesh.xml files
"""

import xml.etree.ElementTree as ET
import math
import sys
import os


class Vector3:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
    
    def __add__(self, other):
        return Vector3(self.x + other.x, self.y + other.y, self.z + other.z)
    
    def __sub__(self, other):
        return Vector3(self.x - other.x, self.y - other.y, self.z - other.z)
    
    def __mul__(self, scalar):
        return Vector3(self.x * scalar, self.y * scalar, self.z * scalar)
    
    def cross(self, other):
        return Vector3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x
        )
    
    def length(self):
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)
    
    def normalize(self):
        length = self.length()
        if length > 0.000001:  # Avoid division by zero
            return Vector3(self.x / length, self.y / length, self.z / length)
        return Vector3(0, 0, 1)  # Default up vector for degenerate cases

def calculate_face_normal(v1, v2, v3):
    """Calculate face normal using cross product of two edges"""
    edge1 = v2 - v1
    edge2 = v3 - v1
    normal = edge1.cross(edge2)
    return normal.normalize()

def recalculate_normals(xml_file_path):
    """Recalculate normals for an Ogre mesh XML file"""
    
    print(f"Processing: {xml_file_path}")
    
    try:
        # Parse the XML file
        tree = ET.parse(xml_file_path)
        root = tree.getroot()
        
        # Process each submesh
        submeshes = root.findall('.//submesh')
        total_vertices_processed = 0
        any_changes_made = False
        
        for submesh_idx, submesh in enumerate(submeshes):
            print(f"  Processing submesh {submesh_idx + 1}...")
            updated_normals = 0
            
            # Check if it uses shared vertices
            uses_shared = submesh.get('usesharedvertices', 'false').lower() == 'true'
            
            if uses_shared:
                # Find shared vertex data
                geometry = root.find('.//sharedgeometry')
                if geometry is None:
                    geometry = root.find('.//mesh/sharedvertexdata')
            else:
                # Find submesh geometry
                geometry = submesh.find('.//geometry')
            
            if geometry is None:
                print(f"    Warning: No geometry found for submesh {submesh_idx + 1}")
                continue
            
            # Get vertex buffer
            vertex_buffer = geometry.find('.//vertexbuffer')
            if vertex_buffer is None:
                print(f"    Warning: No vertex buffer found for submesh {submesh_idx + 1}")
                continue
            
            # Check if normals are present
            if vertex_buffer.get('normals') != 'true':
                print(f"    Warning: No normals in vertex buffer for submesh {submesh_idx + 1}")
                continue
            
            # Extract vertices and positions
            vertices = vertex_buffer.findall('vertex')
            positions = []
            
            for vertex in vertices:
                pos_elem = vertex.find('position')
                if pos_elem is not None:
                    x = float(pos_elem.get('x', 0))
                    y = float(pos_elem.get('y', 0))
                    z = float(pos_elem.get('z', 0))
                    positions.append(Vector3(x, y, z))
                else:
                    positions.append(Vector3(0, 0, 0))
            
            vertex_count = len(positions)
            if vertex_count == 0:
                print(f"    Warning: No positions found for submesh {submesh_idx + 1}")
                continue
            
            # Get faces
            faces_elem = submesh.find('.//faces')
            if faces_elem is None:
                print(f"    Warning: No faces found for submesh {submesh_idx + 1}")
                continue
            
            faces = faces_elem.findall('face')
            
            # Initialize vertex normals accumulator
            vertex_normals = [Vector3(0, 0, 0) for _ in range(vertex_count)]
            vertex_face_count = [0] * vertex_count
            
            # Calculate face normals and accumulate for vertices
            face_count = 0
            for face in faces:
                try:
                    v1_idx = int(face.get('v1', 0))
                    v2_idx = int(face.get('v2', 0))
                    v3_idx = int(face.get('v3', 0))
                    
                    # Validate indices
                    if (v1_idx < vertex_count and v2_idx < vertex_count and v3_idx < vertex_count):
                        # Calculate face normal
                        face_normal = calculate_face_normal(
                            positions[v1_idx], 
                            positions[v2_idx], 
                            positions[v3_idx]
                        )
                        
                        # Accumulate normal for each vertex of the face
                        vertex_normals[v1_idx] = vertex_normals[v1_idx] + face_normal
                        vertex_normals[v2_idx] = vertex_normals[v2_idx] + face_normal
                        vertex_normals[v3_idx] = vertex_normals[v3_idx] + face_normal
                        
                        vertex_face_count[v1_idx] += 1
                        vertex_face_count[v2_idx] += 1
                        vertex_face_count[v3_idx] += 1
                        
                        face_count += 1
                    else:
                        print(f"    Warning: Invalid face indices in face {face_count}")
                        
                except (ValueError, TypeError) as e:
                    print(f"    Warning: Error processing face {face_count}: {e}")
            
            # Normalize vertex normals and update XML
            submesh_changed = False
            for i, vertex in enumerate(vertices):
                if vertex_face_count[i] > 0:
                    # Average the accumulated normals
                    avg_normal = vertex_normals[i] * (1.0 / vertex_face_count[i])
                    final_normal = avg_normal.normalize()
                    
                    # Update the normal in XML
                    normal_elem = vertex.find('normal')
                    if normal_elem is not None:
                        # Check if significantly different (using a small epsilon)
                        old_x = float(normal_elem.get('x', 0))
                        old_y = float(normal_elem.get('y', 0))
                        old_z = float(normal_elem.get('z', 0))
                        
                        if (abs(old_x - final_normal.x) > 0.0001 or 
                            abs(old_y - final_normal.y) > 0.0001 or 
                            abs(old_z - final_normal.z) > 0.0001):
                            
                            normal_elem.set('x', f"{final_normal.x:.6f}")
                            normal_elem.set('y', f"{final_normal.y:.6f}")
                            normal_elem.set('z', f"{final_normal.z:.6f}")
                            updated_normals += 1
                            submesh_changed = True
                    else:
                        # Create normal element if it doesn't exist
                        normal_elem = ET.SubElement(vertex, 'normal')
                        normal_elem.set('x', f"{final_normal.x:.6f}")
                        normal_elem.set('y', f"{final_normal.y:.6f}")
                        normal_elem.set('z', f"{final_normal.z:.6f}")
                        updated_normals += 1
                        submesh_changed = True
                else:
                    # Vertex not part of any face, set default normal
                    normal_elem = vertex.find('normal')
                    if normal_elem is not None:
                        old_y = float(normal_elem.get('y', 0))
                        if abs(old_y - 1.0) > 0.0001:
                            normal_elem.set('x', "0.000000")
                            normal_elem.set('y', "1.000000")  # Default up vector
                            normal_elem.set('z', "0.000000")
                            submesh_changed = True
            
            print(f"    Updated {updated_normals} normals from {face_count} faces")
            total_vertices_processed += updated_normals
            if submesh_changed:
                any_changes_made = True
        
        # Save the modified XML only if changes were made
        if any_changes_made:
            tree.write(xml_file_path, encoding='utf-8', xml_declaration=True)
            print(f"  Successfully recalculated normals for {total_vertices_processed} vertices")
            return "CHANGED"
        else:
            print("  No changes needed. All normals match calculated values.")
            return "UNCHANGED"
        
    except ET.ParseError as e:
        print(f"  ERROR: Failed to parse XML file: {e}")
        return False
    except Exception as e:
        print(f"  ERROR: Unexpected error: {e}")
        return False

def main():
    if len(sys.argv) != 2:
        print("Usage: python recalculate_normals.py <mesh.xml file>")
        sys.exit(1)
    
    xml_file = sys.argv[1]
    
    if not os.path.exists(xml_file):
        print(f"ERROR: File '{xml_file}' not found")
        sys.exit(1)
    
    if not xml_file.lower().endswith('.xml'):
        print(f"ERROR: File '{xml_file}' is not an XML file")
        sys.exit(1)
    
    success = recalculate_normals(xml_file)
    
    if success:
        print("Normal recalculation completed successfully")
        sys.exit(0)
    else:
        print("Normal recalculation failed")
        sys.exit(1)

if __name__ == "__main__":
    main()