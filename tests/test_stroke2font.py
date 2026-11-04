import json

import pytest

from pygmalion.fonts.dataset import load_parquet_font
from pygmalion.fonts.stroke2font import convert


def inputs(tmp_path, entries):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(entries))
    license_file = tmp_path / "LICENSE"
    license_file.write_text("MIT License\nCopyright test\n")
    return source, license_file, tmp_path / "converted"


def glyph(ch="甲", points=None):
    return {"character": ch, "strokes": [{"coordinates": points or [[-2, -3], [2, 1]]}]}


def test_conversion_preserves_stroke_order_orientation_and_dot(tmp_path):
    first = glyph()
    first["strokes"].append({"coordinates": [[1, 1], [1, 2]]})
    args = inputs(
        tmp_path, [first, glyph("●", [[0, 0]]), glyph("甲", [[0, 0], [1, 1]])]
    )
    report = convert(*args)
    assert report["characters"] == 2 and report["records"] == 3
    assert report["duplicates"][0]["character"] == "甲"
    data = load_parquet_font(args[2] / "train.parquet")
    assert data["甲"][0][0][0] < data["甲"][0][-1][0]
    assert data["甲"][0][0][1] < data["甲"][0][-1][1]
    assert len(data["甲"]) == 2
    assert data["●"] == [[[0.0, 0.0], [0.0, 0.0]]]
    assert (args[2] / "LICENSE").read_bytes() == args[1].read_bytes()
    assert (args[2] / "characters.txt").read_text() == "甲●"
    with pytest.raises(ValueError, match="不能覆盖"):
        convert(*args)


@pytest.mark.parametrize(
    "points", [[[float("nan"), 0]], [[True, 0]], [[1, 2, 3]], [[1, "x"]]]
)
def test_invalid_coordinates_do_not_publish_dataset(tmp_path, points):
    args = inputs(tmp_path, [glyph(points=points)])
    with pytest.raises(ValueError):
        convert(*args)
    assert not args[2].exists()
    assert not args[2].with_name(args[2].name + ".building").exists()
