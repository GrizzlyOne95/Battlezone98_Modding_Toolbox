import os
import sys

import bpy


this_dir = os.path.dirname(os.path.abspath(__file__))
if this_dir not in sys.path:
    sys.path.append(this_dir)

import OgreImport


class DummyOperator:
    """Minimal stub to satisfy OgreImport.load(operator, ...)."""

    def report(self, types, message):
        print("REPORT", types, ":", message)


def import_ogre_mesh(mesh_path, xml_converter_path):
    """Use OgreImport.load() to import a single .mesh into the current scene."""
    print(f"--- Importing {mesh_path}")

    before = set(bpy.data.objects.keys())

    OgreImport.load(
        operator=DummyOperator(),
        context=bpy.context,
        filepath=mesh_path,
        xml_converter=xml_converter_path,
        keep_xml=False,
        import_normals=False,
        normal_mode="flat",
        import_shapekeys=True,
        import_animations=True,
        round_frames=True,
        use_selected_skeleton=False,
        import_materials=True,
    )

    after = set(bpy.data.objects.keys())
    new_names = sorted(after - before)

    new_objects = []
    for name in new_names:
        obj = bpy.data.objects.get(name)
        if obj is not None and obj.type in {"MESH", "ARMATURE"}:
            new_objects.append(obj)

    if not new_objects:
        print("WARNING: Import produced no new MESH/ARMATURE objects")

    return new_objects


def export_gltf_for_objects(objects, output_path):
    """Export given objects to a GLB with a no-animation fallback."""
    print(f"--- Exporting to {output_path}")

    if not objects:
        print("WARNING: No objects to export, skipping", output_path)
        return False

    for obj in bpy.data.objects:
        obj.select_set(False)

    for obj in objects:
        try:
            obj.select_set(True)
        except ReferenceError:
            pass

    active = next((obj for obj in objects if obj.type == "ARMATURE"), objects[0])
    bpy.context.view_layer.objects.active = active

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        bpy.ops.export_scene.gltf(
            filepath=output_path,
            export_format="GLB",
            use_selection=True,
            export_skins=True,
            export_animations=True,
            export_yup=True,
        )
        return True
    except Exception as exc:
        print(f"!!! GLTF export WITH animations failed for {output_path}")
        print(f"    Error: {exc}")

    print(f"--- Retrying export WITHOUT animations: {output_path}")
    try:
        bpy.ops.export_scene.gltf(
            filepath=output_path,
            export_format="GLB",
            use_selection=True,
            export_skins=True,
            export_animations=False,
            export_yup=True,
        )
        print(f"*** Exported {output_path} WITHOUT animations due to animation errors")
        return True
    except Exception as exc:
        print(f"!!! GLTF export WITHOUT animations also failed for {output_path}")
        print(f"    Error: {exc}")
        return False


def collect_jobs(input_path, output_dir):
    input_path = os.path.abspath(input_path)
    output_dir = os.path.abspath(output_dir)

    if os.path.isfile(input_path):
        if not input_path.lower().endswith(".mesh"):
            raise ValueError("Single-file mode requires a .mesh input.")
        base_name = os.path.splitext(os.path.basename(input_path))[0] + ".glb"
        return [(input_path, os.path.join(output_dir, base_name))]

    if not os.path.isdir(input_path):
        raise FileNotFoundError(f"Input path not found: {input_path}")

    jobs = []
    for root, _, files in os.walk(input_path):
        for fname in files:
            if not fname.lower().endswith(".mesh"):
                continue

            mesh_path = os.path.join(root, fname)
            rel = os.path.relpath(mesh_path, input_path)
            base, _ = os.path.splitext(rel)
            out_path = os.path.join(output_dir, base + ".glb")
            jobs.append((mesh_path, out_path))

    return jobs


def main():
    argv = sys.argv
    if "--" not in argv:
        print("Usage: blender -b -P batch_ogre_to_gltf.py -- <input_path> <output_dir> <OgreXMLConverter.exe>")
        return 1
    argv = argv[argv.index("--") + 1:]

    if len(argv) < 3:
        print("Usage: blender -b -P batch_ogre_to_gltf.py -- <input_path> <output_dir> <OgreXMLConverter.exe>")
        return 1

    input_path = os.path.abspath(argv[0])
    output_dir = os.path.abspath(argv[1])
    xml_converter = os.path.abspath(argv[2])

    print("Input path: ", input_path)
    print("Output dir: ", output_dir)
    print("XML conv:   ", xml_converter)

    if not os.path.exists(xml_converter):
        print(f"ERROR: OgreXMLConverter.exe not found: {xml_converter}")
        return 1

    os.makedirs(output_dir, exist_ok=True)

    try:
        jobs = collect_jobs(input_path, output_dir)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    if not jobs:
        print("ERROR: No .mesh files found to export.")
        return 1

    success_count = 0
    failure_count = 0

    for mesh_path, out_path in jobs:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT", toggle=False)

        try:
            objects = import_ogre_mesh(mesh_path, xml_converter)
            if export_gltf_for_objects(objects, out_path):
                success_count += 1
            else:
                failure_count += 1
        except Exception as exc:
            failure_count += 1
            print(f"!!! Unhandled error while exporting {mesh_path}")
            print(f"    Error: {exc}")

        print(f"=== Finished {mesh_path} -> {out_path}\n")

    print(f"Summary: {success_count} succeeded, {failure_count} failed")
    return 0 if failure_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
