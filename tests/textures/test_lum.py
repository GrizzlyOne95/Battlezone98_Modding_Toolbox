import json

import pytest
from PIL import Image

from battlezone.terrain.lum import LumaTable, atmosphere, validate_act
from battlezone.terrain.palettes import get_stock_act_bytes
from bztoolbox.cli import main


def test_edit_and_png_roundtrip_keep_indices_even_with_duplicate_colors(tmp_path):
    raw = bytes((i * 37 + i // 256) % 256 for i in range(65536))
    table = LumaTable(bytearray(raw))
    table.set_cell(0, 223, 209)
    expected = raw[:223] + bytes([209]) + raw[224:]
    assert bytes(table.data) == expected
    # All RGB entries are identical: re-quantizing would destroy the indices.
    for palette in (None, bytes([42]) * 768):
        table.export_png(tmp_path / "table.png", palette)
        restored = LumaTable.from_png(tmp_path / "table.png")
        restored.write(tmp_path / "restored.lum")
        assert (tmp_path / "restored.lum").read_bytes() == expected


def test_environment_matches_stock_and_loader_branches():
    mars = get_stock_act_bytes("mars.act")
    table = LumaTable.identity(209)
    colors = atmosphere(mars, table)
    assert colors == dict(sky_index=223, fog_index=209,
                          sky_rgb=(191, 90, 40), fog_rgb=(191, 122, 88))
    assert atmosphere(mars)["fog_rgb"] == (191, 90, 40)
    assert atmosphere(mars, table, 0)["fog_rgb"] == tuple(mars[:3])
    colors = atmosphere(mars, table, 0, sky_color=(1, 2, 3), fog_color=(4, 5, 6))
    assert colors["sky_rgb"] == (1, 2, 3)
    assert colors["fog_rgb"] == (4, 5, 6)
    # Non-stock fog entries work too.
    table.set_cell(0, 223, 107)
    assert atmosphere(mars, table)["fog_rgb"] == tuple(mars[321:324])


@pytest.mark.parametrize("size", [0, 255, 65535, 65537])
def test_bad_lum_sizes_fail(size):
    with pytest.raises(ValueError):
        LumaTable(bytearray(size))


@pytest.mark.parametrize("cell", [(-1, 0, 0), (256, 0, 0), (0, 256, 0), (0, 0, 256), (0, 0, -1)])
def test_invalid_edit_does_not_change_table(cell):
    table = LumaTable.identity()
    before = bytes(table.data)
    with pytest.raises(ValueError):
        table.set_cell(*cell)
    assert bytes(table.data) == before


@pytest.mark.parametrize("mode,size", [("RGB", (256, 256)), ("RGBA", (256, 256)), ("L", (32, 32))])
def test_lossy_or_wrong_sized_png_rejected(tmp_path, mode, size):
    Image.new(mode, size).save(tmp_path / "bad.png")
    with pytest.raises(ValueError):
        LumaTable.from_png(tmp_path / "bad.png")


def test_act_footer_is_accepted_without_truncation():
    raw = get_stock_act_bytes("mars.act") + b"\x01\x00\xff\xff"
    assert validate_act(raw) == raw
    with pytest.raises(ValueError):
        validate_act(raw + b"extra")


def test_cli_authoring_workflow(tmp_path, capsys):
    source, edited, png, restored = [str(tmp_path / n) for n in ["new.lum", "edited.lum", "table.png", "restored.lum"]]
    prefix = ["textures", "lum"]
    assert main(prefix + ["new", source]) == 0
    assert main(prefix + ["set", source, edited, "0", "223", "209"]) == 0
    assert main(prefix + ["to-png", edited, png]) == 0
    assert main(prefix + ["from-png", png, restored]) == 0
    assert LumaTable.read(restored).data == LumaTable.read(edited).data
    assert main(prefix + ["info", restored]) == 0
    assert json.loads(capsys.readouterr().out)["fog_index"] == 209
    assert main(prefix + ["info", restored, "--fog-direction", "0"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["fog_index"] == 0
    assert info["lum_fog_index"] == 209


def test_gui_palette_footer_and_lum_integration(tmp_path, monkeypatch):
    import tkinter as tk
    from bztoolbox.modules.textures import tex_man
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    root.withdraw()
    try:
        app = tex_man.BZReduxSuite(root)
        raw = get_stock_act_bytes("mars.act") + b"\x01\x00\xff\xff"
        app.selected_index = 223
        app.set_workspace_palette(raw)
        root.update()
        app.lum_editor.table = LumaTable.identity(107)
        app.jump_to_fog()
        root.update()
        assert app.selected_index == 107
        assert app.lum_editor.index.get() == "223"  # jump-to-ACT does not alter the table editor
        out = tmp_path / "saved.act"
        monkeypatch.setattr(tex_man.filedialog, "asksaveasfilename", lambda **kw: str(out))
        app.save_act()
        assert out.read_bytes() == raw
        app.lum_editor.row.set("0")
        app.lum_editor.column.set("223")
        app.lum_editor.index.set("209")
        app.lum_editor.apply_cell()
        assert "ACT[209]" in app.lum_editor.colors.get()
        assert len(app.lum_editor.table.data) == 65536
    finally:
        root.destroy()
