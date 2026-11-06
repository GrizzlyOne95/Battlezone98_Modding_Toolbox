# Bug report: bztoolbox (Battlezone98_Modding_Toolbox @ a9919a9)

30 candidates went to provers, and all 30 were **demonstrated** with a failing test on the first try. None needed a retry. Every fix below was applied to a copy and checked: the test passes with it. The repository itself was not modified. Tests and fixed copies are under `/tmp/hunt/prover-N/`.

Severity: **High** means a silent wrong result, data loss, or a hang on ordinary input. **Medium** means a crash on ordinary input, or a wrong result only on unusual input. **Low** is everything else. GUI-dependent tests used stub tkinter/Ogre modules, because neither is installed in the sandbox.

## 1. [High] bztoolbox/modules/publishing/uploader.py : use_selected_item_id_for_upload (line 3656)

- **Input:** Library item that has a steam_status (hidden / under review). _render_library puts visibility_display 'Private · <status label>' (workshop_backend.py:301) in the tree's column 2
- **Should:** Comment: keep the item's current visibility instead of the folder default (Public), so linking can't unhide it
- **Does:** The dict lookup on 'Private · ...' returns None, so visibility stays at the folder default '0 (Public)'. The next Publish then sends Public and unhides a private item. These flagged items are the ones most likely to be private.
- **Proof:** _render_library writes visibility_display (e.g. 'Private · Hidden…') into tree column 2 (uploader.py:3616). The exact-match dict lookup on that value returns None, so visibility stays '0 (Public)'. Test with a stubbed tree row ['Mod','12345','Private · Hidden by moderator',...] fails: visibility is still '0 (Public)' when '2 (Private)' was expected.
- **Test:** `/tmp/hunt/prover-3/test_vis.py`: Current code: AssertionError, visibility '0 (Public)' (out.txt). With the fix: passes, visibility '2 (Private)' (out_fixed.txt). tkinter/PIL were stubbed because tkinter is not installed here.
- **Fix:** In use_selected_item_id_for_upload, strip the status suffix before the lookup: `str(values[2]).split(" · ")[0].strip() if len(values) > 2 else ""`. Patched copy: /tmp/hunt/prover-3/fixed_uploader.py

## 2. [High] bztoolbox/modules/world/world_builder_core.py : load_auto_painter_config / save_auto_painter_config (duplicate defs) (line 3655)

- **Input:** a rule with a mask image or PATH:label; then Save Rules and Load Rules
- **Should:** The earlier definitions (1251/1312) save and load MaskPath for each rule
- **Does:** The later duplicate definitions override the earlier ones. They never write or read MaskPath, so masks are silently lost. Rules loaded from an INI have no 'mask_path' key, so clicking the Mask column header (sort_paint_rules('mask_path')) raises KeyError
- **Proof:** The later definitions in BZ98TRNArchitect (lines 3655 and 3714) replace the earlier ones (1251 and 1312). The later save never writes MaskPath, and the later load never sets 'mask_path'. In the test, a rule with mask_path='C:/m.png' came back without that key after Save Rules and then Load Rules. Because the key is missing, sort_paint_rules('mask_path') does x[key] and raises KeyError.
- **Test:** `/tmp/hunt/prover-5/test_mask.py`: The test stubs tkinter, which is not installed here. On the original code it fails with "AssertionError: mask lost" and the reloaded rule has no mask_path (out_orig.txt). On the fixed copy the reloaded rule keeps mask_path, the sort runs, and the test prints PASS (out_fixed.txt).
- **Fix:** Delete the duplicate load_auto_painter_config and save_auto_painter_config at lines 3655-3730 so the earlier versions, which handle MaskPath, are used. The fixed copy is /tmp/hunt/prover-5/wbc_fixed.py.

## 3. [High] bztoolbox/modules/world/world_builder_core.py : _convert_png_to_hg2_worker (line 1684)

- **Input:** 16-bit PNG, contrast 1.5 (or brightness<1), no smoothing; pixel 0
- **Should:** Brightness/contrast adjust then clip to 0-8191 (or 0-4095 for HGT at line 1680)
- **Does:** After contrast the float array goes negative. astype(np.uint32) on a negative float wraps or is undefined, so the clip happens too late: the lowest valleys come out as maximum height 8191
- **Proof:** The test runs with a 16-bit PNG, contrast 1.5 and no smoothing. Pixel 0 becomes (0-32768)*1.5+32768 = -16384. Calling astype(np.uint32) on that negative float wraps it to a huge value. The later clip then turns it into 8191 (maximum height) instead of 0. Running the current code gives "valley became 8191"; with the fix the test passes. To import the module I had to stub tkinter (stubs/tkinter).
- **Test:** `/tmp/hunt/prover-11/test_neg.py`: original: AssertionError: valley became 8191 (out_orig.txt); fixed copy: pixel0 = 0 PASS (out_fixed.txt)
- **Fix:** In both the HGT and HG2 branches, clip before the cast: `img_final_arr = (np.clip(img_final_arr, 0, 65535).astype(np.uint32) // 16)` (and the same with `// 8`). Patched copy: /tmp/hunt/prover-11/fixed.py

## 4. [High] bztoolbox/modules/world/world_builder_core.py : convert_hg2_to_png (line 1562)

- **Input:** .hg2 with heights above 4095 while HG2IMG legacy mode is on (the default)
- **Should:** Converts an HG2 to an editable PNG without losing data (HG2 heights are 13-bit, as the non-legacy branch's 0x1FFF mask shows)
- **Does:** img_array & 0x0FFF drops bit 12, so heights wrap (5000 -> 904)
- **Proof:** Legacy HG2IMG mode is on by default (hg2img_compat defaults to True). It masks heights with & 0x0FFF, so a 13-bit HG2 height of 5000 is written to the PNG as 904. The height wraps around to a low value instead of being capped. The legacy RG format can only hold 12 bits, so some loss is unavoidable, but the wrap silently corrupts the terrain. Test: /tmp/hunt/prover-13/t.py. It uses a stub for tkinter (not installed here), mocks read_hg2, and calls BZ98TRNArchitect.convert_hg2_to_png on a stand-in object.
- **Test:** `/tmp/hunt/prover-13/t.py`: out_t.txt: AssertionError: 904 (5000 was input). out_t_fixed.txt: height 4095, the test passes.
- **Fix:** In the legacy branch, replace `h = (img_array & 0x0FFF)` with `h = np.clip(img_array & 0x1FFF, 0, 4095)`, which caps heights at 4095 instead of wrapping them. Patched copy: /tmp/hunt/prover-13/fixed.py

## 5. [High] bztoolbox/modules/world/world_builder_core.py : _convert_png_to_hg2_worker (line 1672)

- **Input:** brightness>1 or contrast>1 (values outside 0..65535) with smoothing>0; same at line 1656
- **Should:** Smoothing is applied to the adjusted heightmap
- **Does:** (arr/256).astype(uint8) is not clipped first, so out-of-range values wrap: peaks become pits (90000/256 -> 95)
- **Proof:** The worker was called on a 16-bit PNG at 45000 with brightness=2, smooth=1 and HGT output. The value becomes 90000, and (arr/256).astype(uint8) wraps 351 to 95, so the peak comes out as 1520 instead of 4080. The legacy branch at line 1656 has the same pattern; I fixed it the same way but only tested the 16-bit branch. tkinter is missing here, so I added a minimal stub (stubs/tkinter).
- **Test:** `/tmp/hunt/prover-14/test_wrap.py`: Original code: max height 1520, test fails with AssertionError (out_orig.txt). With fixed.py: max height 4080, test passes (out_fixed.txt).
- **Fix:** Before the uint8 cast, clip to 0..255 in both places: Image.fromarray(np.clip(arr / 256, 0, 255).astype(np.uint8)) and the same for arr16. Applied in /tmp/hunt/prover-14/fixed.py.

## 6. [High] bztoolbox/modules/world/world_builder_core.py : _convert_png_to_hg2_worker (legacy branch) (line 1656)

- **Input:** legacy RG PNG, smooth>0, contrast>1
- **Should:** smoothing keeps the adjusted heights
- **Does:** (arr16/256).astype(uint8) is not clipped (the same bug as line 1672, but in the legacy branch), so negative or >65535 values wrap
- **Proof:** The legacy branch has the bug. Input: a 128x128 legacy RG PNG with the left half G=0 and the right half G=255, plus contrast=2 and smooth=0.5. Contrast pushes arr16 out of range: the low side goes to -32768, which is -128 after /256, and the high side goes to about 98272, which is about 383 after /256. The cast to uint8 has no clip, so both values wrap. The result is inverted heights: the low side comes out at 2048 (expected 0) and the high side at 2016 (expected about 4080). Contrast=3 does not show the bug, because those values happen to wrap to 0 and 255. Tkinter is not installed here, so the test stubs it with a mock. Test: /tmp/hunt/prover-27/test_legacy.py
- **Test:** `/tmp/hunt/prover-27/test_legacy.py`: Before the fix: low 2048, high 2016, AssertionError (out_before.txt). After the fix: low 0, high 4080, test passes (out_after.txt).
- **Fix:** In the legacy smoothing branch, change Image.fromarray((arr16 / 256).astype(np.uint8)) to Image.fromarray(np.clip(arr16 / 256, 0, 255).astype(np.uint8)). The fixed copy is /tmp/hunt/prover-27/wbc_fixed.py.

## 7. [High] bztoolbox/modules/publishing/steamworks_tags.py : SteamworksTagUpdater._run_helper (line 266)

- **Input:** Helper process hangs without printing any more stdout lines
- **Should:** Deadline (timeout_seconds+90) makes the helper raise TimeoutError if it does not finish in time
- **Does:** The deadline is only checked after a line arrives, so 'for raw in proc.stdout' blocks forever and the timeout never fires
- **Proof:** The deadline in _run_helper is only checked after a stdout line arrives. If the helper hangs and prints nothing, `for raw in proc.stdout` blocks forever and no TimeoutError is raised. The test runs _run_helper with a stub PowerShell child that sleeps for an hour and with time.time() jumping past the deadline. After 10s the call is still blocked with no exception, so the test fails on the current code.
- **Test:** `/tmp/hunt/prover-23/test_hang.py`: Original code (out_orig.txt): result {}, AssertionError "no TimeoutError: helper blocked past deadline". With the fix (out_fixed.txt): TimeoutError raised, PASS.
- **Fix:** Start a threading.Timer for (deadline - now) that records the timeout and calls proc.kill(). This closes stdout and ends the read loop. After the loop, raise TimeoutError if the timer fired, and cancel the timer in the finally block. Diff: /tmp/hunt/prover-23/fix.diff; patched copy: /tmp/hunt/prover-23/fix/bztoolbox/modules/publishing/steamworks_tags.py

## 8. [High] bztoolbox/modules/textures/makemap_compat.py : convert_file (line 285)

- **Input:** a .map input file converted with the default output_mode 'map' (for example a re-format to 565)
- **Should:** convert input file to an output in the chosen format, which should not destroy the input
- **Does:** destination = source.with_suffix('.map') is the source file itself, so the original MAP gets silently overwritten with a lossy re-quantised version (8888 turned into 565 here)
- **Proof:** convert_file(a.map, MakeMapOptions(map_format=RGB565)) writes its output to source.with_suffix('.map'), which is the input file itself. The original 8888 MAP is silently replaced with the lossy 565 encoding. Test: /tmp/hunt/prover-24/test_overwrite.py, output in out_orig.txt (AssertionError: source MAP overwritten).
- **Test:** `/tmp/hunt/prover-24/test_overwrite.py`: Original code: fails, src unchanged: False (out_orig.txt). Fixed copy: passes, output goes to a_out.map and the source is left intact (out_fixed.txt, test_fixed.py).
- **Fix:** In convert_file, after `destination = source.with_suffix(extension)` add:
    if destination.resolve() == source.resolve():
        destination = source.with_name(source.stem + "_out" + extension)
(Raising an error instead would also work.) The fixed copy is at /tmp/hunt/prover-24/fix/makemap_compat.py.

## 9. [High] bztoolbox/modules/meshes/MeshToObj.py : main / OgreXMLConverter.convert_to_xml (line 497)

- **Input:** single-file mode, input foo.mesh, with the user's own foo.mesh.xml already next to it
- **Should:** the .mesh.xml file is only a temporary intermediate; user files are left alone
- **Does:** convert_to_xml writes foo.mesh.xml beside the input, overwriting the user's file, and cleanup then deletes it (os.remove). The user's existing XML is lost.
- **Proof:** In single-file mode, convert_to_xml(args.input) is called with no output_dir, so it writes <input>.xml (foo.mesh.xml) right next to the input, overwriting any file already there. main() then runs os.remove on it, because cleanup_xml=True and --keep-xml was not given. The user's own foo.mesh.xml is lost.
- **Test:** `/tmp/hunt/prover-19/test_clobber.py`: Only mesh_to_xml_file is stubbed; the test then calls main() with argv foo.mesh -o out.obj. On the original code it fails with AssertionError "user's foo.mesh.xml lost" (out_orig.txt). With the fixed copy (MOD=fixed) it prints PASS (out_fixed.txt).
- **Fix:** In the single-file branch of main(), write the intermediate XML to a temporary directory instead of beside the input: `xml_file = xml_converter.convert_to_xml(args.input, tempfile.mkdtemp())`. That temp directory is not deleted afterwards; it would ideally be removed with shutil.rmtree. The fix is applied in /tmp/hunt/prover-19/MeshToObj_fixed.py.

## 10. [High] bztoolbox/modules/meshes/ogre_mesh_tools_gui.py : run_operations (line 598)

- **Input:** single (non-batch) .mesh input that already has a sibling foo.mesh.xml
- **Should:** OBJ conversion uses a temporary XML
- **Does:** convert_to_xml(input_p) has no output_dir, so it overwrites the user's foo.mesh.xml, then the finally block deletes it
- **Proof:** For a single (non-batch) .mesh input, run_operations calls xml_conv.convert_to_xml(input_p) without an output_dir. convert_to_xml then writes to <input>.xml, right next to the input, which overwrites the user's existing foo.mesh.xml. The finally block then os.remove()s that file. The test calls OgreMeshToolsGUI.run_operations and stubs tkinter/customtkinter, MeshToObj.mesh_to_xml_file and OgreXMLToOBJ.convert. It shows foo.mesh.xml is gone after an OBJ-only run.
- **Test:** `/tmp/hunt/prover-20/test_xml.py`: On the original code, out_orig.txt shows AssertionError: user foo.mesh.xml clobbered/deleted. On the fixed copy (fixpkg/gui_fixed.py, run with GUI=gui_fixed), out_fixed.txt shows PASS.
- **Fix:** In the single-file .mesh branch, write the XML to a temp folder and delete that folder afterwards: tmp_xml_dir = tempfile.mkdtemp(prefix="obj_xml_"); xml_f = xml_conv.convert_to_xml(input_p, output_dir=tmp_xml_dir). In finally, replace os.remove(xml_f) with `if cleanup_xml: shutil.rmtree(tmp_xml_dir, ignore_errors=True)`. Full diff: /tmp/hunt/prover-20/fix.diff. One gap: if conversion fails and returns None, the RuntimeError is raised before the try, so the empty temp folder is left behind.

## 11. [High] bztoolbox/modules/terrain_generator/relight.py : relight (line 81)

- **Input:** relight a folder that has two .hg2/.lgt pairs with the same file name in different directories whose last folder name matches, e.g. a/maps/x.lgt and b/maps/x.lgt
- **Should:** The module docstring says the old file is copied to the backup folder before it is rebaked, so every original can be restored
- **Does:** The backup path is backup/<parent folder name>/<lgt name>, so both files go to bk/maps/x.lgt. The second copy overwrites the first, and the original a/maps/x.lgt is lost for good once it is rebaked.
- **Proof:** The backup path is backup/<parent folder name>/<lgt name>. So a/maps/x.lgt and b/maps/x.lgt both go to bk/maps/x.lgt, and the second copy overwrites the first. After relight only b's original is in the backup, and a's original is gone because a/maps/x.lgt has already been rebaked. assess_lgt and rebake_lgt_file were stubbed in the test.
- **Test:** `/tmp/hunt/prover-10/test_bk.py`: On the current code: AssertionError, the backup holds only [b'b'] (out.txt). With the fixed copy (test_fix.py, which loads fix/relight.py): [b'a', b'b'], exit 0 (out_fix.txt).
- **Fix:** In relight(), mirror the file's full parent path inside the backup folder: target = result.backup / hg2.parent.resolve().relative_to(hg2.parent.resolve().anchor) / lgt.name. The patched copy is /tmp/hunt/prover-10/fix/relight.py.

## 12. [High] bztoolbox/modules/textures/tex_man.py : start_recompress_thread (line 1067)

- **Input:** The backup folder chosen is the mod folder itself
- **Should:** Refuses a backup folder that lies inside the mod folder
- **Does:** The startswith(folder + os.sep) check misses an equal path. dest == path, so every file is treated as 'replayed', no real backup is made, and the gate restore calls copy2(dest, path) on the same file (SameFileError). The originals are overwritten with no copy kept
- **Proof:** The guard in start_recompress_thread only checks `abspath(backup).startswith(abspath(folder) + os.sep)`. A backup folder equal to the mod folder never matches that prefix, so it is not refused. The test stubs the dialogs and tkinter (tkinter is missing here). It picks the same directory for both, and ui_recompress is started with (d, d). I did not run the downstream effects (no real backup, SameFileError on restore); they follow from the claim.
- **Test:** `/tmp/hunt/prover-25/test_eq.py`: Original code: AssertionError, recompress started with backup == mod folder (out_orig.txt). With the fix: "OK refused" (out_fix.txt).
- **Fix:** In tex_man.py start_recompress_thread, replace the startswith check with: `_b, _f = os.path.realpath(backup), os.path.realpath(folder)` and `if _b == _f or _b.startswith(_f.rstrip(os.sep) + os.sep):`. Fixed copy: /tmp/hunt/prover-25/tex_man_fixed.py

## 13. [Medium] bztoolbox/modules/audio/processing.py : compand (line 164)

- **Input:** a mono clip shorter than the look-ahead delay (e.g. 1000 samples at 22050 Hz with medium intensity, where the look-ahead is 0.15 s = 3308 samples)
- **Should:** compand returns the input with gain applied; radio_vo should handle any voice clip
- **Does:** envelope[lookahead:] is empty, so the new envelope is lookahead samples long and x * gain raises a broadcast ValueError
- **Proof:** The bug is real. I ran a 1000-sample mono clip at 22050 Hz through radio_chain with the default medium intensity, which calls compand. With the look-ahead at 3308 samples, envelope[3308:] is empty, so the new envelope ends up 3308 long, and x * gain fails with "ValueError: operands could not be broadcast together with shapes (1000,) (3308,)".
- **Test:** `/tmp/hunt/prover-1/test_short.py`: On the original code the test fails with that ValueError (/tmp/hunt/prover-1/out_orig.txt). On the fixed copy it prints "ok" (/tmp/hunt/prover-1/out_fix.txt).
- **Fix:** In compand: `lookahead = min(int(round(params.delay * rate)), len(x))`. The fixed copy is at /tmp/hunt/prover-1/fix/bztoolbox/modules/audio/processing.py.

## 14. [Medium] bztoolbox/modules/textures/tex_man.py : ui_recompress / start_recompress_thread (line 1109)

- **Input:** Recompress Mod Folder with Dry run ticked: backup stays None and is passed to recompress.convert
- **Should:** The 'Dry run (report only, write nothing)' option reports what each file would become
- **Does:** convert runs os.path.join(backup_dir, name) at line 224, before it checks dry_run, so it raises a TypeError. Every file is logged as FAILED and nothing is reported
- **Proof:** When Dry run is ticked, start_recompress_thread leaves backup=None and passes it to ui_recompress. ui_recompress then calls recompress.convert(path, None, True, ...). convert runs os.path.join(backup_dir, name) at line 224, before it checks dry_run, so it raises a TypeError on every file that is not skipped as UI or terrain. The test calls convert directly with the same arguments the dry-run path sends and gets that TypeError on the current code.
- **Test:** `/tmp/hunt/prover-2/test_dry.py`: Original code (out_orig.txt): TypeError: expected str, bytes or os.PathLike object, not NoneType. With the fix (out_fix.txt): returns normally ({'file': 'tank.dds', 'skipped': 'not a DDS', ...}) with no error.
- **Fix:** In recompress.convert: `dest = os.path.join(backup_dir, name) if backup_dir else None` and `replayed = dest is not None and os.path.exists(dest)`. Patched copy: /tmp/hunt/prover-2/recompress.py

## 15. [Medium] bztoolbox/modules/world/world_builder_core.py : validate_map_name (line 2604)

- **Input:** 'MULTI01' or any name containing a digit
- **Should:** Label/tooltip: map name up to 8 alphanumeric chars (e.g. 'MULTI01')
- **Does:** the isalpha() check rejects every digit, so the example name from the tooltip cannot be typed
- **Proof:** On line 2604, validate_map_name runs `if not P.isalpha() and P != "": return False`, so any name containing a digit is rejected. That includes 'MULTI01', the example in the tooltip, and it contradicts the "Alphanumeric" label. The isalnum() check on the next line already does the intended validation. I ran the test in /tmp/hunt/prover-4/test_vmn.py with a tkinter stub from stubs/: it fails with "AssertionError: MULTI01 rejected" (output in out_orig.txt).
- **Test:** `/tmp/hunt/prover-4/test_vmn.py`: The original code fails with AssertionError: MULTI01 rejected (out_orig.txt). The fixed copy prints PASS, and it still rejects 'MULTI-1' and names longer than 8 characters (out_fixed.txt).
- **Fix:** Delete line 2604 (`if not P.isalpha() and P != "": return False`). The isalnum() check stays. The patched copy is /tmp/hunt/prover-4/fix/wbc_fixed.py.

## 16. [Medium] bztoolbox/modules/world/world_builder_core.py : browse_mission_bg (line 3525)

- **Input:** any HG2 whose zone size is not 64 (e.g. the standard 128px zones, depth 7)
- **Should:** Load an HG2 as the map background
- **Does:** Zone size is hardcoded to 64 and the header depth is ignored, so reshape raises ValueError. Even with 64px zones, the zone-major data is reshaped as row-major, which scrambles the image
- **Proof:** The bug is real. browse_mission_bg always assumes 64px zones and ignores the depth field in the HG2 header. I built test files with the repo's own write_hg2. With 128px zones (depth 7), loading fails with "cannot reshape array of size 65536 into shape (128,128)". With 64px zones (depth 6), the reshape works, but the image does not match the source, because zone-ordered data is reshaped as if it were rows.
- **Test:** `/tmp/hunt/prover-6/test_bg.py`: Original code (out_orig.txt): 128px zones give the ValueError from reshape; 64px zones load but "match False", so the image is scrambled. Fixed copy (out_fix.txt): both cases print "match True". tkinter is not installed here, so I stubbed it (stubs/tkinter). fixrun.py loads the fixed copy in place of the repo file.
- **Fix:** In browse_mission_bg, replace the manual header unpack, f.read() and reshape((z_l*64, z_w*64)) with `_, arr = read_hg2(path)` (already imported from battlezone.terrain.hg2). That function reads the depth from the header and puts the zones back in the right order. Fixed copy: /tmp/hunt/prover-6/fix/bztoolbox/modules/world/world_builder_core.py

## 17. [Medium] bztoolbox/modules/meshes/ogre_preview.py : OgrePreviewFrame._start_context / load_mesh (line 668)

- **Input:** First PREVIEW of a mesh that fails to load (ctx init OK), then PREVIEW of a valid mesh
- **Should:** After a successful later load the preview renders
- **Does:** _start_context sets self._ctx then returns before scheduling _render_loop; later load_mesh goes to the else branch, which never starts the render loop or removes the error label/placeholder, so the viewport stays frozen/blank showing the old error
- **Proof:** In _start_context, when the mesh fails to load, self._ctx is set (line 660) but the function returns at line 668 before it schedules _render_loop. On the next load_mesh, _ctx is not None, so the else branch runs. That branch only loads the mesh and resets the camera. It never schedules the render loop and never removes the error label or placeholder, so the viewport stays frozen on the old error. tkinter isn't installed here, so the test stubs tkinter, customtkinter and Ogre and calls the real methods on a fake frame object.
- **Test:** `/tmp/hunt/prover-7/test_bug.py`: Original file: AssertionError: render loop never scheduled after valid load (see out_orig.txt). Fixed copy: PASS (see out_fixed.txt).
- **Fix:** In load_mesh's else branch, after _apply_camera(): call self._placeholder.place_forget(); destroy self._error_label if set and reset it to None; show self._hint; and if self._render_job is None, set self._render_job = self.after(16, self._render_loop). Applied in /tmp/hunt/prover-7/fixed_ogre_preview.py.

## 18. [Medium] bztoolbox/modules/publishing/steam_errors.py : _BY_NAME / eresult_info (line 327)

- **Input:** eresult_info('Generic Failure') or SteamCMD line '... (Generic Failure).'
- **Should:** Alias table maps SteamCMD's spelling 'generic failure' to EResult 2; eresult_info accepts names like 'Access Denied'
- **Does:** Returns None: the key is 'generic failure' with a space, but lookups go through _normalise, which strips spaces, so the key can never match. diagnose_steamcmd_output falls back to the generic 'SteamCMD error' message.
- **Proof:** The alias key 'generic failure' keeps its space, but _normalise strips every non-alphanumeric character before the lookup. So that key can never match, and eresult_info('Generic Failure') returns None.
- **Test:** `/tmp/hunt/prover-8/t.py`: Current code: the call prints None and the assert fails (/tmp/hunt/prover-8/out.txt). With the fix it returns SteamError code=2 'Fail' (/tmp/hunt/prover-8/out_fix.txt).
- **Fix:** steam_errors.py line 327: change the key "generic failure" to "genericfailure". The patched copy is /tmp/hunt/prover-8/fix/bztoolbox/modules/publishing/steam_errors.py.

## 19. [Medium] bztoolbox/modules/terrain_generator/hgt.py : upsample (line 372)

- **Input:** 128x128 legacy grid with h[0,0]=0, h[0,1]=1 (or h[0,0]=1, h[0,1]=0), rounding='half-up'
- **Should:** docstring: rounding='half-up' evaluates the plane exactly and rounds halves up
- **Does:** Midpoint value 0.5 comes out as 0 in both cases. delta=(doubled+1)>>1 rounds the delta up, and that delta is then subtracted from h00 (result = h00 - delta), so the height is rounded down (floor), not half-up. legacy_residual uses this mode by default, so its numbers are off too.
- **Proof:** The half-up path takes the ceiling of the delta and then subtracts it from h00 (result = h00 - delta). That makes the height the floor of the plane value, not the half-up rounding the docstring promises. The test calls upsample(h,1,1,rounding='half-up') on a 128x128 grid with h[0,0]=0, h[0,1]=1 and reads output sample [0,1]. It expects 1 (0.5 rounded up) and gets 0. The fix makes both input orders give 1.
- **Test:** `/tmp/hunt/prover-9/test_up.py`: Current code: assertion fails at the first case, (0,1) -> 0 (out_orig.txt). With the fix: (0,1) -> 1 and (1,0) -> 1 (out_fix.txt).
- **Fix:** hgt.py line 372: `delta = (doubled + 1) >> 1` -> `delta = -((1 - doubled) >> 1)`. This takes the floor of the delta, so h00 - delta rounds halves up. Patched copy: /tmp/hunt/prover-9/fix/bztoolbox/modules/terrain_generator/hgt.py

## 20. [Medium] bztoolbox/modules/world/legacy_batch_gui.py : generate_legacy_batch_worker (line 182)

- **Input:** run_legacy_batch raises (e.g. the output root is the same as the source root)
- **Should:** On a batch failure the info label should show 'BATCH FAILED: <exc>'
- **Does:** Python 3 unbinds the except variable 'exc' when the except block ends. The deferred root.after lambda then raises NameError inside the Tk callback, so the label is never updated.
- **Proof:** The bug is real. When the source root and output root are the same, run_legacy_batch raises. The deferred lambda reads `exc` after the except block has ended, and Python 3 has unbound it by then, so the callback raises NameError and the label stays unchanged. With the fix the label reads 'BATCH FAILED: Batch source root and output root must be different directories'.
- **Test:** `/tmp/hunt/prover-12/test_bug.py`: Original code: the test exits 1 with "NameError: cannot access free variable 'exc'" (see /tmp/hunt/prover-12/out_orig.txt). Fixed copy (/tmp/hunt/prover-12/fixed.py): the test exits 0 and prints PASS (see out_fixed.txt).
- **Fix:** Bind the message when the lambda is created: `self.root.after(0, lambda msg=f"BATCH FAILED: {exc}": self.legacy_batch_info.set(msg))`

## 21. [Medium] bztoolbox/modules/world/world_builder_core.py : run_auto_painter (line 1230)

- **Input:** hg2_path pointing at a .hg2 file
- **Should:** Comment says it loads height data from the selected image or HG2 and has an explicit is_hg2 branch
- **Does:** PIL Image.open cannot read the raw HG2 format, so it always fails with 'cannot identify image file'. The is_hg2 branch can never be reached
- **Proof:** run_auto_painter always calls PIL Image.open on the path. PIL cannot read a real .hg2 file written with battlezone.terrain.hg2.write_hg2, so the method fails with "cannot identify image file" and the is_hg2 scaling branch is never reached. read_hg2 is already imported in the module but this method never uses it.
- **Test:** `/tmp/hunt/prover-15/test_ap.py`: The test stubs tkinter and calls the unbound method with a real .hg2 file. On the original code, showerror gets "Failed: cannot identify image file '/tmp/hunt/prover-15/t.hg2'" and the test fails (out_orig.txt). On the fixed copy (fixed.py) the test prints PASS (out_fixed.txt).
- **Fix:** Choose the reader by file extension before loading: `if is_hg2: _h, arr = read_hg2(path); arr = np.asarray(arr).astype(np.float32)` `else: arr = np.array(Image.open(path).convert("I;16")).astype(np.float32); arr = arr/65535.0*4095.0`. The fixed copy is /tmp/hunt/prover-15/fixed.py, lines 1230-1236.

## 22. [Medium] bztoolbox/app/pages/dependencies.py : project_changed / _done (line 165)

- **Input:** Start a graph build for project A, then switch to project B while the job is still running
- **Should:** comment at line 165: 'never show another mod's graph'
- **Does:** project_changed clears the view but does not cancel the running job. on_show returns early because a job is running, so B is never scanned. When A's job finishes, _done shows A's graph and sets _fingerprint while project B is open.
- **Proof:** I confirmed the bug by running a test against the real DependenciesPage. tkinter isn't installed here, so I replaced it with a small stand-in, and I faked the job manager. In the test, A's scan starts, then project B is opened while it is still running. project_changed clears the view but does not cancel A's job. on_show sees a job running and returns, so B is never scanned (only 1 job is ever submitted). When A's job finishes, _done shows A's graph (root /modA) while B is open. The real JobManager checks whether a job was cancelled before calling on_done (jobs.py ~120-131), so cancelling A's job is enough to stop its graph appearing.
- **Test:** `/tmp/hunt/prover-16/test_dep.py`: Current code: AssertionError "A's graph shown while B is open" (/tmp/hunt/prover-16/out.txt). With the fix: exits 0 and prints "jobs submitted: 2 A cancelled: True graph root shown: None" (out_fixed.txt). Run with PYTHONPATH=stubs:/workspace/Battlezone98_Modding_Toolbox (add fix: in front to test the fix).
- **Fix:** In project_changed, right after the _clear() check and before calling on_show: `if self.job is not None and self.job.status in ("queued","running"): self.job.cancel(); self.job = None`. This cancels the old project's scan so on_show can start B's. The patched copy is /tmp/hunt/prover-16/fix/bztoolbox/app/pages/dependencies.py and the diff is in /tmp/hunt/prover-16/fix.diff.

## 23. [Medium] bztoolbox/modules/fonts/atlas.py : hstack_rows (line 168)

- **Input:** top Ink at x=0 width 10, bottom Ink at x=5 width 10 (their x differs, as after the separate .trimmed() crops of O in _build_ef)
- **Should:** Join two horizontal bands of the same glyph, top above bottom
- **Does:** The canvas width is max(top.width, bottom.width) and ignores the x offset between the bands, so the band that sits further right gets cut off: here 5 of the bottom's 10 columns are lost. This can clip the Cyrillic Ef ring.
- **Proof:** hstack_rows sets the canvas width to max(top.width, bottom.width) but places the bottom band at x offset 5. With top at x=0 and bottom at x=5 (both 10 wide), the result is only 10 wide, so 5 of the bottom band's columns are cut off. The function is called from _build_ef (line 438) and at line 669.
- **Test:** `/tmp/hunt/prover-18/test_h.py`: Current code: width is 10 and the test's assertion fails. Patched copy (fixed_atlas.py): width is 15, the bottom band's right columns are fully inked, and the test passes. Output is in /tmp/hunt/prover-18/out.txt.
- **Fix:** width = round(max(top.x + top.width, bottom.x + bottom.width)) - round(min(top.x, bottom.x))

## 24. [Medium] bztoolbox/modules/localization/localization.py : process_manual (line 1145)

- **Input:** a pasted line containing '~' but no '.bzn', e.g. 'Tank~Heavy'
- **Should:** bad lines are skipped and counted as failed, and the batch continues
- **Does:** make_names_key raises ValueError outside the inner try. It goes to the outer handler as 'Critical Error', so the whole remaining batch is aborted and no completion summary is shown
- **Proof:** In process_manual, a line containing '~' but no '.bzn' goes to make_names_key, which raises ValueError. That call sits outside the inner try, so the outer handler catches it and logs 'Critical Error'. The rest of the batch is skipped ('Scout' is never translated) and no BATCH COMPLETE summary is shown.
- **Test:** `/tmp/hunt/prover-21/test_manual.py`: Original code: the only log line is "Critical Error: Localization names cannot contain '~'..." and the test fails with AssertionError: batch aborted (out_orig.txt). Fixed copy: the bad line is skipped, Scout is written once, BATCH COMPLETE is logged and the test prints PASS (out_fixed.txt). tkinter, deep_translator, google.auth and the other GUI/network imports are stubbed with MagicMock.
- **Fix:** In process_manual's else-branch, wrap the make_names_key call: `try: safe_key = self.make_names_key(english_text)` / `except ValueError as e: failed_count += 1; self.progress['value'] += 1; self.log(f"Skipping invalid line: {line} ({e})"); continue`. The fix is applied in /tmp/hunt/prover-21/fixed.py.

## 25. [Medium] bztoolbox/modules/meshes/recalculate_normals.py : recalculate_normals (line 137)

- **Input:** face v1="-1" v2="0" v3="1"
- **Should:** Validate indices
- **Does:** Negative indices pass the < vertex_count check and wrap to the last vertex via Python negative indexing; bogus face gets used and normals written
- **Proof:** The index check is only `idx < vertex_count`. That lets v1=-1 through, and Python treats it as the last vertex. In the test, the face (-1,0,1) is counted as valid, 3 normals are rewritten and the file is saved, and the function returns CHANGED. It should skip the face as invalid.
- **Test:** `/tmp/hunt/prover-22/test_neg.py`: Original code: AssertionError, result CHANGED ("Updated 3 normals from 1 faces"), output in /tmp/hunt/prover-22/out_orig.txt. Fixed copy: "Invalid face indices" warning, result UNCHANGED, PASS, output in /tmp/hunt/prover-22/out_fixed.txt.
- **Fix:** In recalculate_normals.py (~line 137), change the check to: if (0 <= v1_idx < vertex_count and 0 <= v2_idx < vertex_count and 0 <= v3_idx < vertex_count):  (fixed copy at /tmp/hunt/prover-22/fixed_rn.py)

## 26. [Medium] bztoolbox/modules/world/legacy_preflight.py : emit_resolved_palette (line 259)

- **Input:** source TRN with [Color] Palette=moon (no extension)
- **Should:** Emit the palette used for MAP decoding so the output package is self-contained; resolve_legacy_palette normalizes the declared name to '<name>.act'
- **Does:** Writes the palette to output/'moon' with no .act extension, so the output folder never gets moon.act, even though the resolver itself treats the name as moon.act
- **Proof:** With a TRN declaring [Color] Palette=moon and moon.act in the source folder, emit_resolved_palette reports "pass" ("TRN requests MOON.ACT"). But it copies the palette to output/'moon', and the output folder never gets moon.act. The resolver adds the .act extension to the name; the emit step builds the file name from the raw declared value.
- **Test:** `/tmp/hunt/prover-26/test_pal.py`: Original code: AssertionError, output dir contains ['moon'] (out_orig.txt). Patched copy: output dir contains ['moon.act'] and the test prints OK (out_fix.txt).
- **Fix:** In legacy_preflight.py, import normalize_act_name from legacy_palette and use it to name the output file: target_name = normalize_act_name(os.path.basename(declared[0])) if declared else os.path.basename(resolution.path). Diff: /tmp/hunt/prover-26/fix.diff; patched copy: /tmp/hunt/prover-26/fix/bztoolbox/modules/world/legacy_preflight.py

## 27. [Medium] bztoolbox/modules/holotext/hud_gen.py : generate_lua_block (line 341)

- **Input:** variant_count=10 and the text holds 11 or more of the same character, e.g. 'AAAAAAAAAAA'
- **Should:** The Lua block should only name explosion ODFs that generate() built. generate() builds variants 1..variant_count for each character.
- **Does:** usage[b] keeps counting with no cap or wrap, so the block emits MakeExplosion("uiA11"), which names an ODF that was never written. Characters not in the map also fall back to 'un' and quietly render as an underscore.
- **Proof:** I ran generate_lua_block with variant_count=10 and the text 'AAAAAAAAAAA' (11 A's). It emits MakeExplosion("uiA11"), but build_sheet and build_individual only write variants 1..variant_count, so no uiA11 ODF exists. tkinter isn't installed here, so the test replaces the tkinter and PIL imports with mocks and calls the method with a fake self. I did not test the second part of the claim (characters not in the map falling back to 'un').
- **Test:** `/tmp/hunt/prover-28/test_lua.py`: On the original code: AssertionError ['uiA11']. On the fixed copy (/tmp/hunt/prover-28/fixed.py): PASS. Full output is in /tmp/hunt/prover-28/output.txt.
- **Fix:** In generate_lua_block, wrap the variant number: MakeExplosion("{b}{(usage[b]-1) % self.variant_count.get() + 1}", ...)

## 28. [Medium] bztoolbox/modules/localization/localization.py : perform_scan (line 1220)

- **Input:** Any ODF whose unitName contains '~' (or a name make_names_key rejects)
- **Should:** Scan lists every ODF unit name and reports a summary; extract_unit_name errors are caught
- **Does:** make_names_key raises ValueError outside any try in the scan thread. The thread dies with no log message, the list is only partly filled, and btn_bulk stays disabled
- **Proof:** In perform_scan, the make_names_key(unit_name) call is outside any try block. An ODF with unitName "Bad~Tank" makes it raise ValueError. When this runs in the scan thread, the thread dies before it logs "Scan complete" and before it calls btn_bulk.config. The test calls perform_scan directly, with tkinter, deep_translator, google and requests stubbed out because they are not installed here. It fails on the current code with exactly this ValueError.
- **Test:** `/tmp/hunt/prover-29/test_scan.py`: Original code: exit code 1, uncaught ValueError from make_names_key, no "Scan complete" log (out_orig.txt). Fixed copy: exit code 0, the bad ODF is logged as skipped, the scan completes and the test prints PASS (out_fixed.txt).
- **Fix:** In perform_scan, wrap the key line: `try: key = self.make_names_key(unit_name)` / `except ValueError as e: self.log(f"Skipping ODF '{path}': {e}"); continue`. The diff is in /tmp/hunt/prover-29/fix.diff and the patched copy is /tmp/hunt/prover-29/fixed/localization.py.

## 29. [Medium] bztoolbox/modules/meshes/ogre_preview.py : OgrePreviewFrame._drag_move (pan) (line 780)

- **Input:** Middle-drag vertically with the default pitch of 20 degrees (any pitch other than 0)
- **Should:** Comment: 'Pan in camera's local XY plane' using the camera up vector
- **Does:** x and z get +dy*up but y gets -dy*up_y, so the target moves along (up_x, -up_y, up_z). That vector is not the camera up vector and has a part along the view direction, so a vertical pan drifts toward or away from the camera and goes off-axis
- **Proof:** At pitch=20 and yaw=30, a vertical pan of dy=10 moves the target along (up_x, -up_y, up_z). That vector has a component of -2·sin(p)·cos(p)·dy·scale along the camera view direction, so a vertical pan drifts toward or away from the camera, as claimed. The test calls OgrePreviewFrame._drag_move with the tkinter, customtkinter and Ogre modules stubbed. It fails on the current code and passes with the fix.
- **Test:** `/tmp/hunt/prover-30/test_pan.py`: Original code: AssertionError, the view-direction component is nonzero (/tmp/hunt/prover-30/out_orig.txt). Fixed copy (/tmp/hunt/prover-30/fixed.py): the component is about 5.6e-17, so the test passes (/tmp/hunt/prover-30/out_fixed.txt).
- **Fix:** In the pan branch, flip the sign of the y update so all three axes move along the same up vector: `self._orbit_target[1] -= dy * up_y * scale` → `self._orbit_target[1] += dy * up_y * scale`

## 30. [Low] bztoolbox/app/widgets.py : JobsPanel.refresh (line 325)

- **Input:** manager.jobs=[j1,j2,j3] (appended oldest first), then refresh (on 'Clear finished' / panel creation)
- **Should:** Live list of jobs; _upsert inserts new jobs at index 0 (newest first)
- **Does:** reversed() combined with insert at index 0 puts the OLDEST job on top, while live inserts put the newest on top, so the order flips after a refresh
- **Proof:** refresh() loops over reversed(jobs) and _upsert inserts each one at index 0, so the job inserted last (the oldest) ends up on top. That is the reverse of the live order, where the newest job is on top. With jobs j1,j2,j3: live order is job3,job2,job1; after refresh it is job1,job2,job3. tkinter is not installed here, so I used a minimal tkinter stub (/tmp/hunt/prover-17/stub) and a fake tree object.
- **Test:** `/tmp/hunt/prover-17/test_order.py`: Original code: AssertionError (out_orig.txt). Fixed copy: passes, before and after are both ['job3','job2','job1'] (out_fix.txt).
- **Fix:** widgets.py JobsPanel.refresh: `for job in reversed(self.manager.jobs):` -> `for job in self.manager.jobs:` (fixed copy: /tmp/hunt/prover-17/fix/bztoolbox/app/widgets.py)


# What was read

All 151 non-empty non-test `.py` files under `bztoolbox/` (about 46,700 lines), in 20 slices. All 20 readers reported reading their whole slice. Five reviewers reported reading only part of their largest file: uploader.py (1500 of 4038 lines), world_builder_core.py (1900 of 3780), ogre_preview.py (550 of 830), terrain_generator/gui.py (160 of 743) and tex_man.py (700 of 1520). Those files had a full first read but only a partial second look. No agent failed.


# Rejected
None. Every candidate that was checked was demonstrated.


# Not checked (65 suspicions)
Only 30 candidates could be proved. That cap kept the run within 100 agents. The suspicions below were never proved: they were either rated 3 but cut by the cap, or rated 2. Treat them as leads, not confirmed bugs.

- [3] bztoolbox/modules/publishing/workshop_backend.py : classify_steamcmd_login_output (l.97): Mobile and guard markers are checked before the success markers and before returncode==0, so the result is 'mobile_approval', and success is False even though the login worked. With a guard code given, a 'Steam Guard code:' prompt followed by success becomes 'guard_required', which test_steamcmd_login then turns into 'failed'.

- [3] bztoolbox/modules/terrain_generator/research/convert_legacy_hgt.py : module import (l.25): parents[1] is the terrain_generator directory, not the repo root (that would be parents[4]), so the import fails with ModuleNotFoundError: No module named 'bztoolbox'.

- [3] bztoolbox/modules/terrain_generator/research/analyze_local_corpus.py : module import / main (l.32): ROOT=parents[1] is terrain_generator, so the bztoolbox import fails. The default outputs (ROOT/output, ROOT/docs/HG2_CORPUS_SUMMARY.md) are also written inside the package folder instead of the repo root.

- [3] bztoolbox/modules/terrain_generator/research/generate_samples.py : generate (l.12): ENTRYPOINT = terrain_generator/heightmap_generator.py, and that file does not exist (ls shows only cli.py and others). The first subprocess.run(check=True) therefore fails with CalledProcessError and no samples are produced.

- [3] bztoolbox/modules/textures/makemap_compat.py : build_parser (l.347): Because options like -4444/-565/-8888/-888 look like negative numbers, argparse treats '-10' and '-1' as option strings, so it fails with 'expected one argument' (SystemExit 2). Negative values can't be passed at all.

- [2] bztoolbox/modules/publishing/uploader.py : _record_successful_publish / run_steamworks_publish (l.3216): The worker sets item_id_var only through root.after. save_current_project_state then rebuilds current_project_data from _build_project_payload, which reads item_id_var (still '0'). That overwrites the item_id that was just written into current_project_data, so the profile is saved with item_id '0'. A later autosave fixes it only if the after-callback's trace fires while a mod path is set.

- [2] bztoolbox/modules/world/world_builder_core.py : auto_balance_rules (l.3757): Ranges cover only 0-819.1, so every vertex above 819 matches no rule and falls back to material 0

- [2] bztoolbox/modules/world/world_builder_core.py : validate_rules (2nd def) (l.3745): It reports indices from the list sorted by min_h, not the rule positions the user sees, so the wrong rules are named

- [2] bztoolbox/modules/world/world_builder_core.py : AutoPainter.calculate_slope_map (l.425): Grid spacing and height scale are ignored: a gradient of a few units per sample gives atan of about 80-89 degrees, so slope rules are meaningless

- [2] bztoolbox/modules/world/world_builder_core.py : update_preview (l.3394): groups[i]['A'] raises KeyError

- [2] bztoolbox/app/host.py : EmbeddedRoot.configure (l.202): Returns None instead of the dict of options, so a tool that reads it breaks

- [2] bztoolbox/app/pages/hd_terrain.py : _populate/_form_project (l.91): tile_size is set to '' instead of keeping the default '1024'. int('') then raises ValueError on Save or Build, so the loaded recipe cannot be built.

- [2] bztoolbox/app/jobs.py : JobManager.clear_finished (l.147): Calls listener(None) directly, outside the try/except that _drain uses, so a listener that reads job attributes raises AttributeError

- [2] bztoolbox/app/pages/sprites.py : entry_from_form (l.24): int(s, 0) rejects leading-zero decimals with ValueError -> 'must be whole numbers' error

- [2] bztoolbox/app/pages/odf_explorer.py : _render_list (l.296): query compared against name without .lower(), unlike label/rel; names appear lowercased by library so likely harmless

- [2] bztoolbox/external.py : probe_version (l.136): '\n' is truthy, so stderr is ignored and the version comes out empty

- [2] bztoolbox/cli.py : _cmd_validate (l.392): The comprehension checks only against the existing list, not against items already added, so 'foo' is added twice

- [2] bztoolbox/launch.py : build_launch (l.186): the unknown-key check on line 183 uses up the generator, so set(flags) is empty and every flag is silently dropped

- [2] bztoolbox/modules/meshes/ogre_mesh_tools_gui.py : run_operations (l.563): there is no per-file try, so the first exception aborts conversion of all remaining files

- [2] bztoolbox/modules/meshes/MeshToObj.py : _parse_geometry / write_obj (l.263): the uvs/normals lists become shorter than vertices, so have_uvs/have_normals is False for the whole mesh and all UVs/normals are dropped from the faces

- [2] bztoolbox/modules/localization/localization.py : _parse_marker_translation (l.497): strip(' \t\r\n:-') removes these real characters from the translated name

- [2] bztoolbox/modules/missions/bzn_scan.py : BZNAnalyzer.analyze (l.317): Every stock ODF is shown red as MISSING; also exists check is case-sensitive, so 'AVTANK.odf' vs 'avtank.odf' reported missing on Linux

- [2] bztoolbox/modules/publishing/publish_guard.py : other_profiles_for_item / check_publish (l.717): is_item_id accepts it but comparison str(project item_id).strip() == str(item_id) uses the unstripped value, so linked-elsewhere block never triggers; same in unlink_item (project_store.py:599)

- [2] bztoolbox/modules/publishing/steam_service.py : parse_vdf_tokens (l.249): next_token is the string '}', so next_token[1] raises IndexError instead of ValueError. Callers that catch only ValueError would see a different exception.

- [2] bztoolbox/modules/terrain_generator/analysis.py : _shelf_metrics (l.89): sorted_vals[:max(1,0)] still picks the single most common level, so close_to_shelf_pct is non-zero even though there are no shelves

- [2] bztoolbox/modules/terrain_generator/research/convert_legacy_hgt.py : cmd_batch (l.128): Only HGTFormatError is caught, so any other error stops the whole batch and no CSV is written. Writing the HG2 at lines 149-150 is not guarded either. This was not tested; it depends on what hgt.py raises.

- [2] bztoolbox/modules/textures/makemap_compat.py : _quantize_pixel (l.222): trans_index & 0xFF silently wraps to 44, so the wrong index is written; nothing checks the range

- [2] bztoolbox/modules/terrain_generator/urban.py : cyberpunk_megacity (l.443): np.interp is given non-increasing xp, so the y it returns is meaningless and the overpass is put in the wrong place

- [2] bztoolbox/modules/textures/tex_man.py : process_map_file (l.703): The data is decoded as 4-byte BGRA at w = rb/2, so frombytes fails with 'not enough image data', or the pixels come out wrong

- [2] bztoolbox/modules/textures/tex_man.py : process_dxtbz2 (l.1402): The restore is not in a finally block, so the Texture tab keeps the DXT tab's settings afterwards

- [2] bztoolbox/modules/textures/tex_man.py : process_texture (l.1188): Halved only once to 2048, which is still above the cutoff

- [2] bztoolbox/modules/textures/sprite_sheets.py : crop_box (l.572): left = width and right = min(width, left+1) = width, so the crop is empty (0 px)

- [2] bztoolbox/modules/world/bz2_sky_environment.py : act_with_sky_fog (l.67): The 4-byte trailer is dropped without notice and the output is always 768 bytes

- [2] bztoolbox/modules/world/legacy_preflight.py : _validate_lgt (l.224): Reported as an lgt-size error, so the port is marked NOT READY

- [2] bztoolbox/modules/world/legacy_batch_gui.py : setup_legacy_tab_with_batch (output Browse lambda) (l.60): askdirectory returns '' on cancel, which wipes the output root already entered

- [2] bztoolbox/updates.py : check (l.126): update_last_check is saved before the fetch, so a failed check stops any retry for 24 hours

- [2] bztoolbox/updates.py : parse_version (l.51): the pre-release suffix is ignored, so the final release is not treated as newer than its rc

- [2] bztoolbox/paths.py : remove_user_data (l.75): the guard only rejects the home folder, its parents and drive roots, so rmtree deletes any other folder BZTOOLBOX_HOME points to

- [2] bztoolbox/modules/publishing/uploader.py : _summarize_readiness (l.988): rows[0] is 'Warning', not 'Ready', so the detail says 'Resolve blocking items or use one-click fixes before publishing.' even though there are 0 blocking items.

- [2] bztoolbox/modules/publishing/uploader.py : suggest_workshop_link (l.2987): Only item_id_var is set. The other profile stays linked to the same item, so two profiles target it. Visibility stays at the folder default '0 (Public)' until the async sync runs, and if there is no API key the next publish sends Public.

- [2] bztoolbox/modules/world/world_builder_core.py : update_hg2_preview (l.2979): For a flat map norm = value/65535 can fall outside [0,1], and the uint8 cast wraps, so the preview shows the wrong shade

- [2] bztoolbox/app/widgets.py : _dispatch_wheel (l.47): Because of `(-1 if delta > 0 else 1)`, delta 0 counts as scrolling down one unit, so the view drifts down when the wheel has not moved

- [2] bztoolbox/cli.py : main (l.641): The help shortcut only fires when len(argv)==1. Otherwise 'help' goes to argparse, which fails with 'invalid choice' and exit code 2

- [2] bztoolbox/app/shell.py : run (l.673): No availability check is made (the constructor does make one), so it goes to an unavailable page. A suffix match takes the first page in the list whose id ends with the text, even if several match

- [2] bztoolbox/modules/audio/audio.py : export_csv (l.403): file.endswith('.ogg') is case-sensitive, so TRACK.OGG gets the type 'WAV'

- [2] bztoolbox/launch.py : _ini_has (l.588): Returns True, so prepare_map_test never writes the minPlayers default

- [2] bztoolbox/modules/fonts/atlas.py : Recipe.g (l.353): When ink is None, ink.at_left(0) raises AttributeError. build_atlas crashes instead of reporting the glyph as missing.

- [2] bztoolbox/modules/localization/localization.py : _translate_free_http_chunk (l.774): The marker retry adds a '[[BZn]] ' prefix to every line, which roughly doubles the request (8289 chars). It goes over the limit the chunker enforced, so the fallback request can fail

- [2] bztoolbox/modules/localization/localization.py : process_bulk (l.1313): _encode_localization_row raises partway through the loop. The rows before it are already appended, the rest are dropped, and the table is left half-updated

- [2] bztoolbox/modules/meshes/MeshToObj.py : _parse_submesh (l.205): vertex_offset is len(self.vertices), so the face indices point at the next submesh's vertices or past the end. This writes an invalid OBJ

- [2] bztoolbox/modules/meshes/ogre_mesh_tools_gui.py : run_operations (l.547): batch_convert uses rglob('*.mesh'), which is case-sensitive, so uppercase .MESH files are skipped. The run then raises 'No .mesh files were converted'

- [2] bztoolbox/modules/terrain_generator/builder.py : TerrainBuilder.carve_path (l.78): inside influence = 1-0.18*smoothstep(1)=0.82 at dist==half_width, but shoulder branch starts at 1.0 just outside, so depth jumps by 18% of depth at the floor edge (a ditch/step instead of a continuous profile)

- [2] bztoolbox/modules/terrain_generator/gui_logic.py : is_contrast_only_change (l.40): returns True even when nothing changed at all, since vertical_scale isn't part of the key; it can't tell 'contrast-only' from 'no change'

- [2] bztoolbox/modules/terrain_generator/lgt.py : compute_lgt_lightmap (l.202): `ambient` is range-checked and then never used, so every allowed value gives the same output.

- [2] bztoolbox/modules/terrain_generator/natural_finish.py : _apply_symmetry (l.91): The middle row is replaced by its own left-right flip instead of being made symmetric about the centre, so that row is not rotationally symmetric.

- [2] bztoolbox/modules/terrain_generator/research/audit_all_natural.py : module import (l.12): Nothing puts the repo root on sys.path, so the import fails with ModuleNotFoundError: bztoolbox unless the package is installed. audit_stock_detail.py has the same top-level import.

- [2] bztoolbox/modules/terrain_generator/urban.py : _stair_steps (l.318): Position uses t=(i+0.5)/n but height uses i/(n-1). The first step (at t=0.125) gets height sh and the last (at t=0.875) gets eh, so the height and position spacings don't match and each step is too steep/shifted.

- [2] bztoolbox/modules/world/bz2_sky_environment.py : read_sky_environment (l.47): minutes=round(hour*60)=1440, so redux_time_hhmm=2400, which is not a valid time; nothing wraps it modulo 24h

- [2] bztoolbox/modules/world/custom_atlas_builder.py : build_custom_atlas (l.262): returns '<prefix>_atlas_d.png' and the material refers to it, but no file is written

- [2] bztoolbox/modules/world/legacy_port.py : finalize_legacy_port_folder / generate_redux_ini_for_bzn (l.404): copy_legacy_support_files runs first and has already copied the INI, so the status is always 'preserved' ('existing output INI preserved'). Also, if the INI extension case differs (e.g. Foo.INI) on a case-sensitive filesystem, the isfile check misses the copy and a second INI is created.

- [2] bztoolbox/modules/world/mat_codec.py : generate_mat (l.178): each ambiguous tile also adds 1 to solid_tiles, so it is counted twice and solid+cap+diagonal+ambiguous comes out larger than total_tiles

- [2] bztoolbox/modules/world/map_preview.py : _hillshade (l.189): the light vector's y component is +0.5, which points along +row (south) in gradient space, so the light comes from the south-west and the relief looks inverted

- [2] bztoolbox/modules/world/terrain_obj.py : resolve_hg2_geometry (l.382): falls back to DEFAULT_ZONE_BITS, ignoring mesh.zone_bits; then spacing check raises or zone counts are computed with the wrong zone size

- [2] bztoolbox/modules/world/world_builder.py : convert_hg2_to_png (l.651): heights & 0x0FFF wraps the high values modulo 4096 instead of clamping or scaling them, so peaks come out as low ground in the exported PNG

- [2] bztoolbox/modules/world/world_builder.py : _read_image_for_painter (l.854): Images are scaled to raw 0..4095, so after the /5 the painter only sees 0..819. Rules for higher elevations never match on image input, while the same terrain as an HG2 does match them
