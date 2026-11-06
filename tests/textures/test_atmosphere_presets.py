import json

import pytest

from battlezone.terrain.atmosphere_presets import WORLD_ATMOSPHERES, tune_world_act
from battlezone.terrain.lum import LumaTable, atmosphere
from battlezone.terrain.palettes import get_stock_act_bytes
from bztoolbox.cli import main


@pytest.mark.parametrize("world", WORLD_ATMOSPHERES)
def test_presets_only_change_effective_atmosphere_entries(world):
    original = get_stock_act_bytes(world) + b"\x01\x00\xff\xff"
    spec = WORLD_ATMOSPHERES[world]
    result = tune_world_act(world, original)
    colors = atmosphere(result, LumaTable.identity(spec["fog_index"]))
    assert colors["sky_rgb"] == spec["sky"]
    assert colors["fog_rgb"] == spec["fog"]
    for index in range(256):
        if index not in (223, spec["fog_index"]):
            assert result[index * 3:index * 3 + 3] == original[index * 3:index * 3 + 3]
    assert result[768:] == original[768:]


def test_custom_lum_conflict_is_explicit():
    with pytest.raises(ValueError, match="separate sky and fog"):
        tune_world_act("titan", get_stock_act_bytes("titan"), fog_index=223)


def test_batch_preserves_existing_palettes(tmp_path, capsys):
    moon = bytes([17]) * 768
    mars = bytes([94]) * 768
    (tmp_path / "moon.act").write_bytes(moon)
    (tmp_path / "mars.act").write_bytes(mars)
    assert main(["textures", "act", "tune-all", str(tmp_path), "--keep-existing"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report) == 9
    assert sum(r["action"] == "preserved" for r in report) == 2
    assert (tmp_path / "moon.act").read_bytes() == moon
    assert (tmp_path / "mars.act").read_bytes() == mars
    assert len(list(tmp_path.glob("*.act"))) == 9
