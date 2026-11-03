"""应用默认字号只用于创建元素，已有文档始终使用自己的明确字号。"""

import pytest

from pygmalion import config
from pygmalion.schemas.canvas import CanvasDocument, TextBox


def test_editor_default_font_size_is_persisted_without_changing_machine(client):
    assert client.get("/api/v1/settings/editor").json()["values"] == {"font_size_mm": 8}
    machine = dict(config.CONFIG["machine"])
    response = patch_defaults(client, {"font_size_mm": 6.5})
    assert response.status_code == 200
    assert response.json()["values"] == {"font_size_mm": 6.5}
    assert (
        client.get("/api/v1/settings/editor").json()["values"]
        == response.json()["values"]
    )
    assert config.load()["editor"]["font_size_mm"] == 6.5
    assert config.CONFIG["machine"] == machine


@pytest.mark.parametrize("value", [3.9, 40.1, "NaN", "Infinity", None, "abc"])
def test_editor_default_rejects_invalid_values_without_saving(client, value):
    response = patch_defaults(client, {"font_size_mm": value})
    assert response.status_code == 422
    assert client.get("/api/v1/settings/editor").json()["values"]["font_size_mm"] == 8


@pytest.mark.parametrize("size", [4, 40])
def test_editor_default_accepts_boundaries(client, size):
    response = patch_defaults(client, {"font_size_mm": size})
    assert response.status_code == 200
    assert response.json()["values"]["font_size_mm"] == size


def test_changing_default_does_not_relayout_existing_text_boxes(client):
    document = CanvasDocument(
        elements=[
            TextBox(id="first", text="甲乙", font_size_mm=6),
            TextBox(id="second", text="丙", x_mm=130, width_mm=40, font_size_mm=12),
        ]
    ).model_dump()
    original = client.post("/api/v1/plans", json=document)
    assert original.status_code == 201
    assert original.json()["status"] == "ready"
    assert patch_defaults(client, {"font_size_mm": 20}).status_code == 200
    changed = client.post("/api/v1/plans", json=document)
    assert changed.status_code == 201
    assert (
        client.get(changed.json()["preview_url"]).text
        == client.get(original.json()["preview_url"]).text
    )
    assert changed.json()["status"] == "ready"


def patch_defaults(client, values):
    current = client.get("/api/v1/settings/editor").json()
    return client.patch(
        "/api/v1/settings/editor", json=values, headers={"If-Match": current["etag"]}
    )
