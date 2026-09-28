# Replace a Redux BZN object class safely

A Redux object record has a layout determined by its ODF's `classLabel`. Editing
only that text or replacing an ODF can leave the BZN with the old layout. The
**Missions > Replace object class** page rebuilds selected records from a
matching prototype while keeping their mission identity and placement.

## GUI workflow

1. Choose the mission BZN, a Redux mission BZN containing an object of the
   desired class, and the target ODF with the intended `classLabel`.
2. Choose an output BZN. The page suggests a separate `_reclass.bzn` file;
   selecting the original source is allowed and creates a backup.
3. Select the source objects and one prototype object. The prototype should
   have the same record class as the target ODF. Click **Preview replacement**.
4. Review the fields preserved, copied, cleared, and removed for each object.
   Click **Write BZN** to save the verified result. A timestamped `.bak-*`
   copy is created if the output already exists, along with a JSON report.

The source and prototype must both be Redux mission maps at the same BZN
version. ASCII and binary maps are supported. Saved games are excluded.
The target ODF is read to determine the class and is never modified.

Identity, sequence number, label, name, team, player flag, position, transform,
and mission objective flags stay with each source object. Health, ammo,
physics, and class-specific state come from the prototype. Copied object/path
references and command fields are cleared; references *to* the replaced object
continue to work because its object address is preserved.

Preview writes nothing. It serializes and reparses the proposed map in memory,
checks preserved fields and all untouched objects, and rejects newly broken
references. Existing unresolved references are shown as warnings. It also
refuses to leave another object with the target ODF on an incompatible record
layout. After a successful write, load the map in Redux to verify the ODF,
mission script, and gameplay behavior.

## Command line

The indices in the object lists start at zero:

```text
bztoolbox bzn replace-class mission.bzn --list
bztoolbox bzn replace-class prototype.bzn --list
```

Preview a replacement; repeat `--object` to select multiple source objects:

```text
bztoolbox bzn replace-class mission.bzn \
  --template prototype.bzn --prototype-index 12 \
  --object 4 --object 5 --target-odf ivpdrop.odf \
  --output mission_reclass.bzn
```

Add `--apply` to write the file after preview verification. `--output` may be
the source path for an in-place change with a timestamped backup. Inputs are
fingerprinted during preview and checked again before writing, so changed
source, prototype, or ODF files require another preview.
