import numpy as np
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from pygmalion.fonts.outline import thin, skeleton_paths, convert_outline
from pygmalion.fonts.dataset import load_parquet_font


def test_thinning_preserves_components_and_reduces_thickness():
    mask = np.zeros((25, 25), dtype=bool)
    mask[4:21, 10:15] = True
    mask[10:15, 4:21] = True
    mask[1, 1] = True
    skeleton = thin(mask)
    assert skeleton[1, 1]
    assert skeleton.sum() < mask.sum()
    assert not (skeleton & ~mask).any()
    import cv2

    assert (
        cv2.connectedComponents(mask.astype("uint8"))[0]
        == cv2.connectedComponents(skeleton.astype("uint8"))[0]
    )
    assert np.array_equal(skeleton, thin(skeleton))


def test_trails_cover_every_edge_without_drawing_between_components():
    mask = np.zeros((12, 14), dtype=bool)
    mask[5, 2:9] = True
    mask[2:9, 5] = True
    mask[10, 12] = True
    paths = skeleton_paths(mask)
    assert len(paths) == 3  # 十字需要两条路径，孤立点另起一笔。
    edges = []
    for path in paths:
        for a, b in zip(path, path[1:]):
            assert mask[a[1], a[0]] and mask[b[1], b[0]]
            assert max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 1
            if a != b:
                edges.append(frozenset([a, b]))
    assert len(edges) == 12 and len(set(edges)) == 12


def test_closed_loop_is_not_broken():
    mask = np.zeros((12, 12), dtype=bool)
    mask[2, 2:9] = True
    mask[8, 2:9] = True
    mask[2:9, 2] = True
    mask[2:9, 8] = True
    paths = skeleton_paths(mask)
    assert len(paths) == 1 and paths[0][0] == paths[0][-1]


def make_font(path):
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "a"])
    builder.setupCharacterMap({ord("甲"): "a"})
    pen = TTGlyphPen(None)
    pen.moveTo((100, 100))
    pen.lineTo((500, 100))
    pen.lineTo((500, 800))
    pen.lineTo((100, 800))
    pen.closePath()
    builder.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "a": pen.glyph()})
    builder.setupHorizontalMetrics({".notdef": (1000, 0), "a": (1000, 100)})
    builder.setupHorizontalHeader(ascent=900, descent=-100)
    builder.setupNameTable(
        {
            "familyName": "Test Outline",
            "styleName": "Regular",
            "uniqueFontIdentifier": "TestOutline",
            "fullName": "Test Outline",
            "psName": "TestOutline",
        }
    )
    builder.setupOS2(
        sTypoAscender=900, sTypoDescender=-100, usWinAscent=900, usWinDescent=100
    )
    builder.setupPost()
    builder.save(path)


def test_offline_conversion_records_missing_glyphs_and_preserves_license(tmp_path):
    font = tmp_path / "test.ttf"
    make_font(font)
    license_file = tmp_path / "OFL.txt"
    license_file.write_text("SIL OPEN FONT LICENSE Version 1.1\nTest font fixture")
    output = tmp_path / "font"
    result = convert_outline(font, license_file, output, "甲乙", 128)
    assert result["characters"] == 1 and result["skipped"] == ["乙"]
    assert result["source_family"] == "Test Outline"
    data = load_parquet_font(output / "train.parquet")
    assert data["甲"] and set(data) == {"甲"}
    assert (output / "OFL.txt").read_bytes() == license_file.read_bytes()
    assert all(abs(v) <= 0.45 for stroke in data["甲"] for p in stroke for v in p)
    with pytest.raises(ValueError, match="不能覆盖"):
        convert_outline(font, license_file, output)


def test_optimized_trails_reduce_lifts_without_shortcuts_or_unbounded_retrace():
    import math

    mask = np.zeros((120, 35), dtype=bool)
    mask[5:115, 17] = True
    for y in (20, 40, 60, 80):
        mask[y, 15:20] = True
    before = skeleton_paths(mask)
    after = skeleton_paths(mask, optimize=True)

    def edges(paths):
        return [(tuple(a), tuple(b)) for p in paths for a, b in zip(p, p[1:]) if a != b]

    base = edges(before)
    optimized = edges(after)
    assert len(after) < len(before)
    assert {frozenset(e) for e in base} == {frozenset(e) for e in optimized}
    assert (
        sum(math.dist(*e) for e in optimized)
        <= sum(math.dist(*e) for e in base) * 1.15 + 1e-8
    )
    assert all(max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 1 for a, b in optimized)
    assert after == skeleton_paths(mask, optimize=True)


def test_ordering_changes_only_path_order_and_direction():
    from pygmalion.fonts.outline import order_paths

    source = [[(100, 0), (101, 0)], [(0, 0), (1, 0)], [(4, 0), (3, 0)]]
    before = [p[:] for p in source]
    after = order_paths(source)
    assert source == before
    assert {frozenset(p) for p in source} == {frozenset(p) for p in after}
    assert after[0] == [(0, 0), (1, 0)]
    assert order_paths([]) == []
