"""Exercise the real native page and its worker job, including recipe reload."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from tests.app.test_gui import _make_root, pump


def test_page_builds_bundle_and_reloads_portable_recipe(tmp_path):
    from bztoolbox.app import theme
    from bztoolbox.app.jobs import JobManager
    from bztoolbox.app.pages.hd_terrain import HdTerrainPage
    root = _make_root()
    root.withdraw()
    jobs = JobManager(root)
    page = None
    try:
        theme.apply(root)
        shell = SimpleNamespace(jobs=jobs, status=lambda text: None)
        page = HdTerrainPage(root, shell)
        page.pack(fill="both", expand=True)
        sources = tmp_path / "art"
        sources.mkdir()
        (sources / "map.csv").write_text(",0,0,.5,.5\nMA00SA0.MAP,.5,0,.5,.5\n")
        Image.new("RGB", (16, 16), (220, 100, 50)).save(sources / "ma00sa0_d.png")
        form = {"sources": str(sources), "layout": str(sources / "map.csv"),
                "material": "MY_MARS", "diffuse_resource": "mars_d.dds",
                "default_alias": "MA00SA0.MAP", "tile_size": "16", "prefix": "my_mars",
                "out": str(tmp_path / "bundle")}
        for key, value in form.items():
            page.vars[key].set(value)
        with patch("bztoolbox.app.pages.hd_terrain.messagebox.showerror") as errors:
            page._build()
            assert page.job is not None
            pump(root, 10, until=lambda: page.job.status not in ("queued", "running"))
            assert page.job.status == "done", page.job.error
            errors.assert_not_called()
        bundle = tmp_path / "bundle"
        assert (bundle / "resources/my_mars_ma00sa0_d.dds").is_file()
        with patch("bztoolbox.app.pages.hd_terrain.filedialog.askopenfilename",
                   return_value=str(bundle / "authoring.json")):
            page._load()
        assert page.vars["material"].get() == "MY_MARS"
        assert Path(page._form_project()["tiles"]["MA00SA0.MAP"]["D"]).is_file()
        # Typing a different source folder must not silently reuse the loaded recipe.
        page.vars["sources"].set(str(sources))
        assert page._form_project()["tiles"]["MA00SA0.MAP"]["D"] == str(sources / "ma00sa0_d.png")
    finally:
        jobs.shutdown()
        if page is not None:
            page.destroy()
        root.destroy()
