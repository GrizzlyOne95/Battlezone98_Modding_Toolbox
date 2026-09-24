"""
ogre_preview.py - Embedded Ogre Mesh Preview for BZOgreMeshTools GUI

Strategy:
  - Use ApplicationContext ONLY for its initApp() bootstrap (plugin loading,
    Root creation, RTShader init).
  - In our setup() override, call root.createRenderWindow() directly with
    externalWindowHandle — we NEVER call OgreBites.ApplicationContext.createWindow()
    which would spawn an unwanted SDL/OS window.
  - Drive the render loop via Tkinter's after() scheduler.
  - Mouse orbit / zoom / pan implemented natively in Tkinter.
"""

import os
import math
import tkinter as tk
import customtkinter as ctk
import importlib.util

try:
    import Ogre
    import Ogre.Bites as OgreBites
    import Ogre.RTShader as RTShader
except ImportError:
    Ogre = None
    OgreBites = None
    RTShader = None
    print("WARNING: Ogre python module not found! Run: py -3.10 -m pip install ogre-python")

import sys

# In PyInstaller, we want the log next to the EXE, not in the temp _MEIPASS dir
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(APP_DIR, "OgrePreview.log")

def log_msg(msg):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{msg}\n")
            f.flush() # Force write to disk
    except Exception as e:
        # Fallback to sys.stderr if file write fails
        sys.stderr.write(f"[LOG_ERROR] {e} while logging: {msg}\n")
    print(msg)

log_msg(f"--- ogre_preview.py loaded. System: {sys.platform}. Log: {LOG_FILE} ---")


# ---------------------------------------------------------------------------
# We subclass ApplicationContext only for its bootstrap (createRoot, plugin
# loading, RTShader init, resource loading).  setup() is fully overridden
# and never calls super().setup() or ApplicationContext.createWindow().
# ---------------------------------------------------------------------------

class _EmbeddedOgreContext(OgreBites.ApplicationContext if OgreBites else object):
    """Initializes Ogre into an external HWND without creating a popup window."""

    def __init__(self, hwnd: int, width: int, height: int):
        super().__init__("OgrePreview")
        self._hwnd = hwnd
        self._width = max(width, 100)
        self._height = max(height, 100)
        self._render_window = None
        self._scn_mgr = None
        self._cam = None
        self._camnode = None
        self._mesh_entity = None
        self._mesh_node = None
        self._rg = "OgrePreviewGroup"
        self._rg_created = False

    # ------------------------------------------------------------------
    # Override setup() — never calls super().setup() or createWindow()
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Override setup() — never calls super().setup() or createWindow()
    # ------------------------------------------------------------------
    def setup(self):
        log_msg("[OgrePreview] Entering setup...")
        root = self.getRoot()

        # 1. Select render system
        log_msg("[OgrePreview] Selecting render system...")
        for pref in [
            "Direct3D11 Rendering Subsystem",
            "OpenGL 3+ Rendering Subsystem",
            "OpenGL Rendering Subsystem",
        ]:
            rs = root.getRenderSystemByName(pref)
            if rs:
                root.setRenderSystem(rs)
                log_msg(f"[OgrePreview] Selected: {pref}")
                break
        else:
            renderers = root.getAvailableRenderers()
            if not renderers:
                log_msg("[OgrePreview] CRITICAL: No Ogre render system available.")
                raise RuntimeError("No Ogre render system available.")
            root.setRenderSystem(renderers[0])
            log_msg(f"[OgrePreview] Fallback selected: {renderers[0].getName()}")

        # 2. Initialise Root — no auto-window
        log_msg("[OgrePreview] Initialising Root...")
        root.initialise(False)
        log_msg("[OgrePreview] Root initialised.")

        # 3. Create render window embedded in our Tk frame.
        log_msg("[OgrePreview] Creating render window...")
        params = Ogre.NameValueMap()
        params["externalWindowHandle"] = str(self._hwnd)
        params["FSAA"] = "0"
        params["vsync"] = "false"
        params["gamma"] = "false"
        params["colourDepth"] = "32"
        self._render_window = root.createRenderWindow(
            "OgrePreview", self._width, self._height, False, params
        )
        log_msg(f"[OgrePreview] Render window created: {self._render_window.getName()}")
        self._render_window.setActive(True)
        self._render_window.setAutoUpdated(False)

        # 4. RTShader + resources.
        log_msg("[OgrePreview] Initialising ApplicationContext resources and RTShader...")
        self.locateResources()
        self.initialiseRTShaderSystem()

        self.loadResources()
        log_msg("[OgrePreview] All resources loaded.")

        # 5. Scene manager + RTShader registration
        log_msg("[OgrePreview] Creating SceneManager...")
        self._scn_mgr = root.createSceneManager()
        try:
            shadergen = RTShader.ShaderGenerator.getSingleton()
            shadergen.addSceneManager(self._scn_mgr)
            log_msg("[OgrePreview] SceneManager registered with RTShader.")
        except Exception as e:
            log_msg(f"[OgrePreview] RTShader registration error: {e}")

        # 6. Lighting
        self._scn_mgr.setAmbientLight(Ogre.ColourValue(0.4, 0.4, 0.4))

        main_light = self._scn_mgr.createLight("PVMainLight")
        main_light.setType(Ogre.Light.LT_DIRECTIONAL)
        ln = self._scn_mgr.getRootSceneNode().createChildSceneNode()
        ln.attachObject(main_light)
        ln.setDirection(Ogre.Vector3(-1, -1.5, -1).normalisedCopy())

        fill_light = self._scn_mgr.createLight("PVFillLight")
        fill_light.setType(Ogre.Light.LT_DIRECTIONAL)
        fill_light.setDiffuseColour(Ogre.ColourValue(0.25, 0.25, 0.35))
        fn = self._scn_mgr.getRootSceneNode().createChildSceneNode()
        fn.attachObject(fill_light)
        fn.setDirection(Ogre.Vector3(1, 0.5, 1).normalisedCopy())

        # 7. Camera
        self._cam = self._scn_mgr.createCamera("PVCam")
        self._cam.setAutoAspectRatio(True)
        self._cam.setNearClipDistance(0.1)
        self._cam.setFarClipDistance(100000.0)

        self._camnode = self._scn_mgr.getRootSceneNode().createChildSceneNode()
        self._camnode.attachObject(self._cam)
        self._camnode.setPosition(Ogre.Vector3(0, 0, 500))
        self._camnode.lookAt(Ogre.Vector3(0, 0, 0), Ogre.Node.TS_WORLD)

        # 8. Viewport
        vp = self._render_window.addViewport(self._cam)
        vp.setBackgroundColour(Ogre.ColourValue(0.08, 0.08, 0.10))
        
        # Explicitly set the scheme to RTShader scheme
        try:
            shadergen = RTShader.ShaderGenerator.getSingleton()
            vp.setMaterialScheme(RTShader.ShaderGenerator.DEFAULT_SCHEME_NAME)
            log_msg(f"[OgrePreview] Viewport scheme set to: {RTShader.ShaderGenerator.DEFAULT_SCHEME_NAME}")
        except Exception as e:
            log_msg(f"[OgrePreview] Warning: Failed to set viewport scheme: {e}")

    def locateResources(self):
        """
        Populate the Ogre ResourceGroupManager with paths before loadResources().
        """
        # 1. Base (loads from resources.cfg if it exists)
        super().locateResources()
        
        _rgm = Ogre.ResourceGroupManager.getSingleton()
        
        # 2. Add Ogre internal Media (CRITICAL for RTShader headers)
        try:
            possible_paths = []
            if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                possible_paths.append(os.path.join(sys._MEIPASS, "Ogre", "Media"))
                possible_paths.append(os.path.join(sys._MEIPASS, "Media")) 
            
            ogre_spec = importlib.util.find_spec("Ogre")
            if ogre_spec and ogre_spec.origin:
                ogre_pkg_dir = os.path.dirname(ogre_spec.origin)
                possible_paths.append(os.path.join(ogre_pkg_dir, "Media"))

            ogre_media_dir = None
            for p in possible_paths:
                if os.path.exists(p):
                    ogre_media_dir = p
                    break
            
            if ogre_media_dir:
                log_msg(f"[OgrePreview] Registering Ogre Media folders into 'General' group...")
                # Recursively add ALL subfolders of Media to 'General'
                # Includes RTShaderLib, Main, Terrain, etc.
                for root_dir, _, _ in os.walk(ogre_media_dir):
                    _rgm.addResourceLocation(root_dir, "FileSystem", "General")
                    # Too verbose for final log, but helpful for now
                    # log_msg(f"  + Added: {os.path.basename(root_dir)}")
            else:
                log_msg(f"[OgrePreview] Warning: Ogre Media directory not found in {possible_paths}")
        except Exception:
            import traceback
            log_msg(f"[OgrePreview] Error in locateResources (Ogre Media):\n{traceback.format_exc()}")

        # 3. Register project directory (for BZBase.material)
        if getattr(sys, 'frozen', False):
            _project_dir = getattr(sys, "_MEIPASS", APP_DIR)
        else:
            _project_dir = os.path.dirname(os.path.abspath(__file__))

        try:
            _rgm.addResourceLocation(_project_dir, "FileSystem", "General")
            log_msg(f"[OgrePreview] Registered project dir in 'General': {_project_dir}")
        except Exception as e:
            log_msg(f"[OgrePreview] Warning: addResourceLocation(project) failed: {e}")

    # ------------------------------------------------------------------
    # ApplicationContext expects getRenderWindow() to return our window
    # ------------------------------------------------------------------
    def getRenderWindow(self):
        return self._render_window

    # ------------------------------------------------------------------
    # Mesh loading / swapping
    # ------------------------------------------------------------------
    # Names of sibling/parent subdirectories to auto-scan for resources
    _RESOURCE_DIRS = {"materials", "textures", "programs", "shaders",
                      "fonts", "overlays", "packs"}

    def _collect_resource_locations(self, mesh_dir: str) -> list:
        """
        Build a list of directories to add as resource locations.

        Handles the BZ_ASSETS layout:
            BZ_ASSETS/common/models/foo.mesh   <- mesh
            BZ_ASSETS/common/materials/        <- materials
            BZ_ASSETS/common/textures/         <- textures
            BZ_ASSETS/pc/materials/            <- platform materials
            BZ_ASSETS/pc/textures/             <- platform textures

        Strategy:
        1. Always add the mesh's own directory.
        2. Walk UP the tree (up to 6 levels). At each parent level:
           a. Add the parent itself.
           b. For each sibling dir:
              - If its name is a known resource dir → add it + its subdirs.
              - Otherwise → check one level inside it for resource subdirs
                (this catches BZ_ASSETS/pc/{materials,textures}).
        """
        locations = [mesh_dir]
        seen = {os.path.normcase(mesh_dir)}

        def _add(path):
            key = os.path.normcase(path)
            if key not in seen:
                locations.append(path)
                seen.add(key)

        current = mesh_dir
        for _ in range(6):
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
            _add(current)

            try:
                for entry in os.scandir(current):
                    if not entry.is_dir():
                        continue
                    name_l = entry.name.lower()

                    if name_l in self._RESOURCE_DIRS:
                        # Direct resource dir — add it + one level of subdirs
                        _add(entry.path)
                        try:
                            for sub in os.scandir(entry.path):
                                if sub.is_dir():
                                    _add(sub.path)
                        except OSError:
                            pass
                    else:
                        # Non-resource sibling (e.g. 'pc') — look one level
                        # inside for resource-named subdirs
                        try:
                            for sub in os.scandir(entry.path):
                                if sub.is_dir() and sub.name.lower() in self._RESOURCE_DIRS:
                                    _add(sub.path)
                                    # One more level inside those too
                                    try:
                                        for subsub in os.scandir(sub.path):
                                            if subsub.is_dir():
                                                _add(subsub.path)
                                    except OSError:
                                        pass
                        except OSError:
                            pass
            except OSError:
                pass

        return locations


    def load_mesh(self, mesh_path: str):
        log_msg(f"[OgrePreview] Loading mesh: {mesh_path}")
        if not self._scn_mgr:
            log_msg("[OgrePreview] Error: Scene manager not initialized.")
            return
        self._clear_mesh()

        file_dir = os.path.dirname(os.path.abspath(mesh_path))
        file_name = os.path.basename(mesh_path)

        rgm = Ogre.ResourceGroupManager.getSingleton()
        if not self._rg_created:
            try:
                rgm.createResourceGroup(self._rg)
            except Exception:
                pass
            self._rg_created = True

        try:
            rgm.clearResourceGroup(self._rg)
        except Exception:
            pass

        # Register all discovered resource directories (BZ_ASSETS tree scan)
        locations = self._collect_resource_locations(file_dir)
        print(f"[OgrePreview] Adding {len(locations)} resource location(s):")
        for loc in locations:
            try:
                rgm.addResourceLocation(loc, "FileSystem", self._rg)
                print(f"  + {loc}")
            except Exception:
                pass

        rgm.initialiseResourceGroup(self._rg)

        self._mesh_entity = self._scn_mgr.createEntity(file_name)
        self._mesh_node = self._scn_mgr.getRootSceneNode().createChildSceneNode()
        self._mesh_node.attachObject(self._mesh_entity)
        log_msg(f"[OgrePreview] Mesh entity created: {file_name}")

        # Apply materials programmatically — bypasses broken script import chains
        self._apply_programmatic_materials(self._mesh_entity, locations)

        # Auto-frame camera around mesh
        bb = self._mesh_entity.getBoundingBox()
        diam = bb.getSize().length()
        if diam <= 0.0:
            diam = 100.0

        center = bb.getCenter()
        self._mesh_node.setPosition(-center)

        self._cam.setNearClipDistance(max(0.01, diam * 0.005))
        self._cam.setFarClipDistance(diam * 500.0)

        return diam  # return for camera init in caller

    # Texture file extensions to search, in priority order
    _TEX_EXTS = {".dds", ".png", ".tga", ".jpg", ".bmp"}

    def _find_texture(self, base_name: str, locations: list) -> "str | None":
        """
        Case-insensitive search for a texture by base name across all
        resource locations (and one level of subdirectories).
        Returns the ACTUAL filename on disk so Ogre can locate it, or None.
        """
        target_lower = base_name.lower()

        def _scan_dir(dirpath):
            try:
                for entry in os.scandir(dirpath):
                    if not entry.is_file():
                        continue
                    name, ext = os.path.splitext(entry.name)
                    if name.lower() == target_lower and ext.lower() in self._TEX_EXTS:
                        return entry.name  # actual disk name
            except OSError:
                pass
            return None

        for loc in locations:
            result = _scan_dir(loc)
            if result:
                return result
            # One level deeper (e.g. DIFF/, EMIS/, SPEC/ subdirs)
            try:
                for sub in os.scandir(loc):
                    if sub.is_dir():
                        result = _scan_dir(sub.path)
                        if result:
                            # Also register this subdir in the resource group
                            # so Ogre can actually load the file
                            try:
                                rgm = Ogre.ResourceGroupManager.getSingleton()
                                rgm.addResourceLocation(sub.path, "FileSystem", self._rg)
                            except Exception:
                                pass
                            return result
            except OSError:
                pass
        return None


    def _apply_programmatic_materials(self, entity, locations: list):
        """
        For each sub-entity, create a simple Ogre material in Python code
        with the DiffuseMap texture (found by _D suffix convention).
        Falls back to a solid grey material if no texture is found.
        """
        mm = Ogre.MaterialManager.getSingleton()

        for i in range(entity.getNumSubEntities()):
            sub = entity.getSubEntity(i)
            mat_name = sub.getMaterialName()  # e.g. "avtank00"

            # Unique preview material name to avoid global conflicts
            preview_mat_name = f"__preview__{mat_name}"

            # Reuse if already created this session
            if mm.resourceExists(preview_mat_name):
                sub.setMaterialName(preview_mat_name)
                continue

            # Find diffuse texture: try several common BZ Redux suffixes
            # Also try stripping trailing numbers (e.g. avtank00 -> avtank)
            base_variants = [mat_name, mat_name.rstrip('0123456789')]
            suffixes = ["_a", "_A", "_d", "_D", "_diff", "_DIFF", ""]
            
            diffuse_tex = None
            for bv in base_variants:
                if not bv: continue
                for s in suffixes:
                    diffuse_tex = self._find_texture(bv + s, locations)
                    if diffuse_tex:
                        break
                if diffuse_tex:
                    break

            # Create material
            mat = mm.create(preview_mat_name, self._rg)
            mat.setReceiveShadows(True)

            tech = mat.getTechnique(0)
            pass_ = tech.getPass(0)
            pass_.setAmbient(Ogre.ColourValue(0.4, 0.4, 0.4))
            pass_.setDiffuse(Ogre.ColourValue(1.0, 1.0, 1.0, 1.0))
            pass_.setSpecular(Ogre.ColourValue(0.4, 0.4, 0.4, 1.0))
            pass_.setShininess(32.0)

            if diffuse_tex:
                tu = pass_.createTextureUnitState(diffuse_tex)
                tu.setTextureAddressingMode(
                    Ogre.TextureUnitState.TAM_WRAP,
                    Ogre.TextureUnitState.TAM_WRAP,
                    Ogre.TextureUnitState.TAM_WRAP,
                )
                print(f"[OgrePreview] {mat_name} -> {diffuse_tex}")
            else:
                # Solid grey fallback
                pass_.setDiffuse(Ogre.ColourValue(0.6, 0.6, 0.65, 1.0))
                print(f"[OgrePreview] {mat_name} -> no texture found (grey)")

            mat.compile()
            
            # Force RTShader to handle this material (CRITICAL for D3D11/GL3+)
            try:
                shadergen = RTShader.ShaderGenerator.getSingleton()
                # Use "DefaultLib" and "RTG_ShaderSystem"
                shadergen.createShaderBasedTechnique(preview_mat_name, "DefaultLib", "RTShaderLib")
                shadergen.validateMaterial("DefaultLib", preview_mat_name, mat.getGroup())
            except Exception as e:
                # log_msg(f"[OgrePreview] RTShader error for {preview_mat_name}: {e}")
                pass

            sub.setMaterialName(preview_mat_name)



    def _clear_mesh(self):
        if self._mesh_node and self._scn_mgr:
            try:
                self._mesh_node.detachAllObjects()
                self._scn_mgr.getRootSceneNode().removeAndDestroyChild(self._mesh_node)
            except Exception:
                pass
            self._mesh_node = None
        if self._mesh_entity and self._scn_mgr:
            try:
                self._scn_mgr.destroyEntity(self._mesh_entity)
            except Exception:
                pass
            self._mesh_entity = None

    def resize(self, w: int, h: int):
        if self._render_window:
            try:
                self._render_window.resize(w, h)
                self._render_window.windowMovedOrResized()
            except Exception:
                pass

    def render_frame(self):
        root = Ogre.Root.getSingleton()
        root.renderOneFrame()
        if self._render_window:
            self._render_window.update()


# ---------------------------------------------------------------------------
# CTk widget: hosts Ogre context + mouse orbit/zoom/pan
# ---------------------------------------------------------------------------

class OgrePreviewFrame(ctk.CTkFrame):
    """Embeds an Ogre 3D viewport. Supports LMB-orbit, RMB-zoom, MMB-pan."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        self._ctx: "_EmbeddedOgreContext | None" = None
        self._render_job = None

        # Camera orbit state
        self._orbit_yaw   = 30.0   # degrees
        self._orbit_pitch = 25.0   # degrees
        self._orbit_dist  = 200.0
        self._orbit_target = [0.0, 0.0, 0.0]  # look-at point
        self._mouse_prev  = None
        self._drag_mode   = None   # 'orbit' | 'zoom' | 'pan'

        if not Ogre:
            lbl = ctk.CTkLabel(
                self,
                text="Ogre bindings not found.\nRun: py -3.10 -m pip install ogre-python",
            )
            lbl.pack(expand=True)
            return

        # Raw Tk frame Ogre renders into — black backing
        self._render_frame = tk.Frame(self, bg="black", cursor="crosshair")
        self._render_frame.pack(fill="both", expand=True)

        # Placeholder shown before any mesh is loaded
        self._placeholder = tk.Label(
            self._render_frame,
            text="Select a .mesh file\nand click PREVIEW",
            fg="#00ff00",
            bg="black",
            font=("Consolas", 11),
        )
        self._placeholder.place(relx=0.5, rely=0.5, anchor="center")

        # Controls hint (shown after mesh loads)
        self._hint = tk.Label(
            self._render_frame,
            text="LMB: Orbit   RMB: Zoom   MMB: Pan",
            fg="#444444",
            bg="black",
            font=("Consolas", 8),
        )

        self._render_frame.bind("<Configure>", self._on_resize)

        # Mouse bindings
        self._render_frame.bind("<ButtonPress-1>",   lambda e: self._drag_start(e, "orbit"))
        self._render_frame.bind("<ButtonPress-3>",   lambda e: self._drag_start(e, "zoom"))
        self._render_frame.bind("<ButtonPress-2>",   lambda e: self._drag_start(e, "pan"))
        self._render_frame.bind("<B1-Motion>",       self._drag_move)
        self._render_frame.bind("<B3-Motion>",       self._drag_move)
        self._render_frame.bind("<B2-Motion>",       self._drag_move)
        self._render_frame.bind("<ButtonRelease-1>", self._drag_end)
        self._render_frame.bind("<ButtonRelease-3>", self._drag_end)
        self._render_frame.bind("<ButtonRelease-2>", self._drag_end)
        self._render_frame.bind("<MouseWheel>",      self._mouse_wheel)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_mesh(self, mesh_path: str):
        if not Ogre:
            return

        if self._ctx is None:
            self._start_context(mesh_path)
        else:
            try:
                diam = self._ctx.load_mesh(mesh_path)
                self._reset_camera(diam)
                self._apply_camera()
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._show_error(str(e))

    # ------------------------------------------------------------------
    # Context initialization
    # ------------------------------------------------------------------

    def _start_context(self, mesh_path: str):
        # Clear log for new session
        log_msg(f"[_start_context] Called for {mesh_path}")
        try:
            with open(LOG_FILE, "w") as f:
                f.write("--- NEW PREVIEW SESSION ---\n")
                f.flush()
        except: pass
        
        log_msg("[OgrePreview] Starting Ogre context...")
        self.update() # Ensure window is mapped
        hwnd = self._render_frame.winfo_id()
        w = max(200, self._render_frame.winfo_width())
        h = max(150, self._render_frame.winfo_height())
        log_msg(f"[OgrePreview] HWND: {hwnd}, Size: {w}x{h}")

        ctx = _EmbeddedOgreContext(hwnd, w, h)
        try:
            log_msg("[OgrePreview] Calling initApp()...")
            ctx.initApp()
            log_msg("[OgrePreview] initApp() completed.")
            diam = ctx.load_mesh(mesh_path)
            log_msg("[OgrePreview] load_mesh() completed.")
        except Exception as e:
            import traceback
            err_details = traceback.format_exc()
            log_msg(f"[OgrePreview] CRITICAL ERROR DURING INIT:\n{err_details}")
            try:
                ctx.closeApp()
            except Exception:
                pass
            self._show_error(str(e))
            return

        self._ctx = ctx
        self._reset_camera(diam)
        self._apply_camera()

        self._placeholder.place_forget()
        self._hint.place(relx=0.5, rely=1.0, anchor="s", y=-4)

        self._render_job = self.after(16, self._render_loop)

    # ------------------------------------------------------------------
    # Render loop
    # ------------------------------------------------------------------

    def _render_loop(self):
        if not self._ctx:
            return
        try:
            self._ctx.render_frame()
        except Exception as e:
            print(f"[OgrePreview] Render error: {e}")
            self._stop_render()
            return
        self._render_job = self.after(16, self._render_loop)

    def _stop_render(self):
        if self._render_job is not None:
            try:
                self.after_cancel(self._render_job)
            except Exception:
                pass
            self._render_job = None

    # ------------------------------------------------------------------
    # Camera helpers
    # ------------------------------------------------------------------

    def _reset_camera(self, diam: float):
        self._orbit_dist   = diam * 1.8
        self._orbit_yaw    = 30.0
        self._orbit_pitch  = 20.0
        self._orbit_target = [0.0, 0.0, 0.0]

    def _apply_camera(self):
        if not self._ctx or not self._ctx._camnode:
            return
        yaw_r   = math.radians(self._orbit_yaw)
        pitch_r = math.radians(self._orbit_pitch)
        d = self._orbit_dist

        x = d * math.cos(pitch_r) * math.sin(yaw_r)
        y = d * math.sin(pitch_r)
        z = d * math.cos(pitch_r) * math.cos(yaw_r)

        tx, ty, tz = self._orbit_target
        pos = Ogre.Vector3(tx + x, ty + y, tz + z)
        target = Ogre.Vector3(tx, ty, tz)

        self._ctx._camnode.setPosition(pos)
        self._ctx._camnode.lookAt(target, Ogre.Node.TS_WORLD)

        # Keep near/far sensible as distance changes
        if self._ctx._cam:
            self._ctx._cam.setNearClipDistance(max(0.01, d * 0.001))

    # ------------------------------------------------------------------
    # Mouse controls
    # ------------------------------------------------------------------

    def _drag_start(self, event, mode: str):
        self._mouse_prev = (event.x, event.y)
        self._drag_mode  = mode
        self._render_frame.focus_set()

    def _drag_end(self, event):
        self._mouse_prev = None
        self._drag_mode  = None

    def _drag_move(self, event):
        if self._mouse_prev is None or not self._ctx:
            return
        dx = event.x - self._mouse_prev[0]
        dy = event.y - self._mouse_prev[1]
        self._mouse_prev = (event.x, event.y)

        if self._drag_mode == "orbit":
            self._orbit_yaw   -= dx * 0.5
            self._orbit_pitch += dy * 0.5
            self._orbit_pitch  = max(-89.0, min(89.0, self._orbit_pitch))

        elif self._drag_mode == "zoom":
            factor = 1.0 + dy * 0.005
            self._orbit_dist *= factor
            self._orbit_dist  = max(0.01, self._orbit_dist)

        elif self._drag_mode == "pan":
            # Pan in camera's local XY plane
            yaw_r   = math.radians(self._orbit_yaw)
            pitch_r = math.radians(self._orbit_pitch)
            scale   = self._orbit_dist * 0.002

            # Camera right vector
            right_x =  math.cos(yaw_r)
            right_z = -math.sin(yaw_r)
            # Camera up vector (approximate world-up projected onto view plane)
            up_x = -math.sin(pitch_r) * math.sin(yaw_r)
            up_y =  math.cos(pitch_r)
            up_z = -math.sin(pitch_r) * math.cos(yaw_r)

            self._orbit_target[0] -= (dx * right_x - dy * up_x) * scale
            self._orbit_target[1] -= dy * up_y * scale
            self._orbit_target[2] -= (dx * right_z - dy * up_z) * scale

        self._apply_camera()

    def _mouse_wheel(self, event):
        if not self._ctx:
            return
        if event.delta > 0:
            self._orbit_dist *= 0.9
        else:
            self._orbit_dist *= 1.1
        self._orbit_dist = max(0.01, self._orbit_dist)
        self._apply_camera()

    # ------------------------------------------------------------------
    # Resize / error display
    # ------------------------------------------------------------------

    def _on_resize(self, event):
        if self._ctx and event.widget == self._render_frame:
            w, h = event.width, event.height
            if w > 10 and h > 10:
                self._ctx.resize(w, h)

    def _show_error(self, message: str):
        for child in self._render_frame.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        lbl = tk.Label(
            self._render_frame,
            text=f"Preview error:\n{message}",
            fg="#ff4444",
            bg="black",
            font=("Consolas", 10),
            wraplength=300,
            justify="center",
        )
        lbl.place(relx=0.5, rely=0.5, anchor="center")

    def destroy(self):
        self._stop_render()
        if self._ctx:
            try:
                self._ctx.closeApp()
            except Exception:
                pass
            self._ctx = None
        super().destroy()
