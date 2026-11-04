"""电路结构、引脚几何、协议、保存和单线预览回归。"""

import json
import shutil
import string
from pathlib import Path
from xml.etree import ElementTree

import pytest
from datasets import Dataset
from pydantic import ValidationError

from pygmalion.drawing.circuit import render_circuit, symbol_geometry
from pygmalion.schemas.canvas import CanvasDocument
from pygmalion.schemas.circuit import CircuitElement
from pygmalion.writing import canvas
from tests.test_mcp import call, result, rpc

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "circuits"


@pytest.fixture
def circuit_client(client):
    chars = string.ascii_letters + string.digits + "Ωμ+-甲乙测试说明中文待确认"
    directory = canvas.ROOT / "model-bin" / "cjk-medians"
    Dataset.from_list(
        [
            {"char": c, "lengths": [2], "x": [-3000, 3000], "y": [0, 0]}
            for c in dict.fromkeys(chars)
        ]
    ).to_parquet(directory / "train.parquet")
    return client


def example(name="rc-lowpass"):
    return json.loads((EXAMPLES / (name + ".json")).read_text())


@pytest.mark.parametrize("name", [p.stem for p in sorted(EXAMPLES.glob("*.json"))])
def test_circuit_examples_are_editable_and_rendered_through_mcp(circuit_client, name):
    client = circuit_client
    element = example(name)
    render = result(call(client, "render_circuit", element=element))
    assert "<svg" in render["svg"] and "<text" not in render["svg"]
    assert len(render["layout"]["components"]) == len(element["circuit"]["components"])
    assert not [d for d in render["diagnostics"] if d["severity"] == "error"], render[
        "diagnostics"
    ]
    document = CanvasDocument(
        elements=[CircuitElement.model_validate(element)]
    ).model_dump()
    created = result(
        call(client, "create_document", document=document, idempotency_key=name)
    )
    plan = result(
        call(client, "prepare_document", document_id=created["id"], revision=1)
    )
    assert plan["status"] == "ready", plan["diagnostics"]
    assert plan["strokes"] > 0
    assert (
        client.get(f"/api/v1/documents/{created['id']}").json()["document"] == document
    )
    assert client.get("/api/v1/jobs").json()["data"] == []
    assert call(
        client,
        "queue_job",
        plan_id=plan["id"],
        mode="execute",
        idempotency_key="forbidden",
    )["isError"]
    assert client.get("/api/v1/jobs").json()["data"] == []


def test_moving_component_keeps_wire_attached_and_scaling_preserves_shape(
    circuit_client,
):
    client = circuit_client
    element = example()
    before = client.post("/api/v1/circuits/render", json=element).json()
    element["circuit"]["components"][1]["x_mm"] += 7
    element["circuit"]["components"][1]["angle"] = 90
    after = client.post("/api/v1/circuits/render", json=element).json()
    pin = after["layout"]["components"][1]["pins"]["start"]
    assert after["layout"]["wires"][0]["points"][-1] == pin
    assert pin != before["layout"]["components"][1]["pins"]["start"]
    for wire in after["layout"]["wires"]:
        for a, b in zip(wire["points"], wire["points"][1:]):
            assert a["x_mm"] == b["x_mm"] or a["y_mm"] == b["y_mm"]
    first = CircuitElement.model_validate(element)
    assert render_circuit(first).strokes == render_circuit(first).strokes
    element["scale"] = 2
    scaled = client.post("/api/v1/circuits/render", json=element).json()
    assert scaled["layout"]["components"][1]["width_mm"] == pytest.approx(
        after["layout"]["components"][1]["width_mm"] * 2
    )


def test_invalid_pins_uncertainties_and_crossings_are_not_silently_connected(
    circuit_client,
):
    client = circuit_client
    element = example()
    element["circuit"]["wires"][0]["end"]["pin"] = "center"
    element["circuit"]["uncertainties"] = [
        {"target_id": "r1", "message": "R1 数值看不清"}
    ]
    render = result(call(client, "render_circuit", element=element))
    codes = {d["code"] for d in render["diagnostics"]}
    assert {"invalid_pin", "unconfirmed"} <= codes
    assert len(render["layout"]["wires"]) == 2
    document = CanvasDocument(
        elements=[CircuitElement.model_validate(element)]
    ).model_dump()
    assert client.post("/api/v1/plans", json=document).json()["status"] == "blocked"
    element["circuit"]["components"].append(dict(element["circuit"]["components"][0]))
    with pytest.raises(ValidationError):
        CircuitElement.model_validate(element)


def test_symbol_catalog_and_legacy_version_compatibility(circuit_client):
    client = circuit_client
    catalog = result(call(client, "list_circuit_symbols"))
    assert len(catalog["symbols"]) == 18
    for item in catalog["symbols"]:
        if item["kind"] == "chip":
            assert item["pins"] == []
            continue
        assert (
            item["pins"] and "center" not in item["pins"] and "xy" not in item["pins"]
        )
        symbol_geometry(item["kind"], 90, 20, "ANSI")
    legacy = CanvasDocument(version=2, name="旧文档").model_dump()
    assert client.post("/api/v1/documents/validate", json=legacy).status_code == 200
    legacy["elements"] = [example()]
    assert client.post("/api/v1/documents/validate", json=legacy).status_code == 422
    assert client.get("/api/v1/capabilities").json()["document_versions"] == [2, 3]
    tools = {t["name"] for t in rpc(client, "tools/list")["tools"]}
    assert {"list_circuit_symbols", "render_circuit"} <= tools and "queue_job" not in tools


def test_multi_pin_chip_renders_and_wires_use_named_pins(circuit_client):
    element = example()
    element["circuit"]["components"] = [{
        "id": "adc", "kind": "chip", "reference": "AD7685", "x_mm": 45,
        "y_mm": 35, "length_mm": 32,
        "chip_pins": [
            {"name": "IN+", "side": "left", "label": "IN+"},
            {"name": "IN-", "side": "left", "label": "IN-"},
            {"name": "VREF", "side": "top", "label": "REF"},
            {"name": "DOUT", "side": "right", "label": "DOUT"},
        ],
    }]
    element["circuit"]["junctions"] = [{"id": "input", "x_mm": 0, "y_mm": 30}]
    element["circuit"]["wires"] = [{"id": "w", "start": {"junction_id": "input"}, "end": {"component_id": "adc", "pin": "IN+"}}]
    rendered = result(call(circuit_client, "render_circuit", element=element))
    assert rendered["layout"]["wires"][0]["points"][-1] == rendered["layout"]["components"][0]["pins"]["IN+"]
    assert not [d for d in rendered["diagnostics"] if d["severity"] == "error"]
    arranged = circuit_client.post("/api/v1/circuits/layout", json=element)
    assert arranged.status_code == 200
    assert [p["name"] for p in arranged.json()["element"]["circuit"]["components"][0]["chip_pins"]] == ["IN+", "IN-", "VREF", "DOUT"]
    element["circuit"]["components"][0]["chip_pins"].append({"name": "IN+", "side": "right"})
    with pytest.raises(ValidationError):
        CircuitElement.model_validate(element)


def test_crossing_wires_do_not_infer_connections(circuit_client):
    element = example()
    element["circuit"]["junctions"] = [
        {"id": ident, "x_mm": x, "y_mm": y}
        for ident, x, y in [("a", 0, 10), ("b", 20, 10), ("c", 10, 0), ("d", 10, 20)]
    ]
    element["circuit"]["wires"] = [
        {"id": "cross1", "start": {"junction_id": "a"}, "end": {"junction_id": "b"}},
        {"id": "cross2", "start": {"junction_id": "c"}, "end": {"junction_id": "d"}},
    ]
    model = CircuitElement.model_validate(element)
    snapshot = model.model_dump()
    result = render_circuit(model)
    assert model.model_dump() == snapshot
    assert len(result.layout["wires"]) == 2
    assert all(len(w["points"]) == 2 for w in result.layout["wires"])
    assert not any(j.x_mm == j.y_mm == 10 for j in model.circuit.junctions)


def test_circuit_ink_outside_frame_is_preserved_in_svg(circuit_client):
    element = example()
    element.update(x_mm=-100, y_mm=-100, width_mm=5, height_mm=5)
    element["circuit"]["components"][1]["x_mm"] = -80
    plan = circuit_client.post(
        "/api/v1/plans", json={"version": 3, "elements": [element]}
    ).json()
    assert plan["status"] == "ready"
    svg = circuit_client.get(plan["preview_url"]).text
    bounds = list(map(float, ElementTree.fromstring(svg).get("viewBox").split()))
    assert bounds[0] <= -180 and bounds[1] <= -100
    assert bounds[0] + bounds[2] >= 210


def test_unlabelled_symbols_render_without_font_dataset(circuit_client):
    shutil.rmtree(canvas.ROOT / "model-bin")
    element = example()
    for c in element["circuit"]["components"]:
        c.update(reference="", value="", label="")
    plan = circuit_client.post(
        "/api/v1/plans", json={"version": 3, "elements": [element]}
    ).json()
    assert plan["status"] == "ready" and plan["strokes"] > 0


def test_auto_layout_is_deterministic_preserves_connections_and_places_vertical_labels(
    circuit_client,
):
    source = example()
    source["circuit"]["components"][1]["angle"] = 90
    source["circuit"]["components"][1]["x_mm"] = source["circuit"]["components"][0][
        "x_mm"
    ]
    source["circuit"]["components"][1]["y_mm"] = source["circuit"]["components"][0][
        "y_mm"
    ]
    a = result(call(circuit_client, "layout_circuit", element=source))
    b = circuit_client.post("/api/v1/circuits/layout", json=source).json()
    assert a == b
    after = a["element"]
    assert [(w["id"], w["start"], w["end"]) for w in after["circuit"]["wires"]] == [
        (w["id"], w["start"], w["end"]) for w in source["circuit"]["wires"]
    ]
    boxes = a["layout"]["components"]
    for i, box in enumerate(boxes):
        for other in boxes[i + 1 :]:
            from pygmalion.drawing.circuit_layout import overlaps

            assert not overlaps(
                tuple(box[k] for k in ["x_mm", "y_mm", "width_mm", "height_mm"]),
                tuple(other[k] for k in ["x_mm", "y_mm", "width_mm", "height_mm"]),
            )
    assert (
        source["circuit"]["components"][1]["x_mm"]
        == source["circuit"]["components"][0]["x_mm"]
    )
    assert not [d for d in a["diagnostics"] if d["severity"] == "error"]
    for box in a["layout"]["components"] + a["layout"]["labels"]:
        assert box["x_mm"] >= after["x_mm"]
        assert box["y_mm"] >= after["y_mm"]
        assert box["x_mm"] + box["width_mm"] <= after["x_mm"] + after["width_mm"] + 0.01
        assert (
            box["y_mm"] + box["height_mm"] <= after["y_mm"] + after["height_mm"] + 0.01
        )
    assert circuit_client.get("/api/v1/jobs").json()["data"] == []
