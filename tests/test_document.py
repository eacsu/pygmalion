import pytest

from pygmalion import config
from pygmalion.schemas.document import DocumentRequest
from pygmalion.writing.document import layout_document, prepare_document


def test_document_preserves_blank_lines_indent_and_name_is_not_printed():
    doc = DocumentRequest(
        name="不可打印的文件名", body="  甲\n\n乙\n", font_size_mm=8, line_gap_mm=3
    )
    placed, overflow = layout_document(doc)
    assert not overflow
    assert "".join(g.char for g in placed) == "甲乙"
    assert placed[0].cx == 32  # 20mm 页边距 + 两个半角空格 + 字格半宽
    assert placed[0].cy == 24
    assert placed[1].cy == 46  # 空行保留一整行高度
    a, _ = prepare_document(doc)
    b, _ = prepare_document(doc.model_copy(update={"name": "另一个名称"}))
    assert a.svg == b.svg and a.gcode == b.gcode
    assert a.poem.title == "" and a.poem.author == ""


@pytest.mark.parametrize("direction", ["horizontal", "vertical"])
def test_document_wraps_without_shrinking_and_overflow_blocks_write(direction):
    prepared, overflow = prepare_document(
        DocumentRequest(body="甲" * 1000, direction=direction, font_size_mm=8)
    )
    assert overflow and not prepared.can_print
    assert prepared.font_size_mm == 8


def test_horizontal_wrapping_and_vertical_blank_columns():
    d = DocumentRequest(body="甲" * 22)
    placed, overflow = layout_document(d)
    assert not overflow
    assert placed[20].cy == 24 and placed[21].cy == 35
    placed, _ = layout_document(DocumentRequest(body="甲\n\n乙", direction="vertical"))
    assert placed[0].cx == 186 and placed[1].cx == 164
    assert placed[0].cy == placed[1].cy == 24


@pytest.mark.parametrize(
    "payload",
    [
        {"font_size_mm": -1},
        {"margin_mm": 100},
        {"body": []},
        {"paper": "A0"},
        {"title": "自动标题"},
        {"char_gap_mm": None},
    ],
)
def test_invalid_document_never_enqueues(payload):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DocumentRequest(**{"body": "甲", **payload})


def test_missing_and_empty_body_are_blocked():
    for text in (" \n  ", "甲\U0010ffff"):
        prepared, _ = prepare_document(DocumentRequest(body=text))
        assert not prepared.can_print


def test_single_active_task_freezes_preview_and_machine_configuration(
    client, monkeypatch
):
    from threading import Event

    from pygmalion.execution import repository as store
    from pygmalion.schemas.canvas import CanvasDocument, TextBox
    from tests.test_public_api import wait

    runtime = client.app.state.services.execution
    runtime.dry_run = False
    entered, release = Event(), Event()

    def send(machine, program, **kwargs):
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(
        runtime.machine,
        "read_anchor_position",
        lambda: {"port": "COM99", "position": (0.0, 0.0)},
    )
    monkeypatch.setattr(runtime.machine, "send_program", send)
    plan = client.post(
        "/api/v1/plans",
        json=CanvasDocument(
            name="设备联调01", elements=[TextBox(id="t", text="甲乙")]
        ).model_dump(),
    ).json()
    job = client.post(
        "/api/v1/jobs",
        json={"plan_id": plan["id"], "mode": "execute"},
        headers={"Idempotency-Key": "frozen"},
    ).json()
    try:
        assert entered.wait(2)
        frozen = store.get_resource("jobs", job["id"])["snapshot"]
        config.CONFIG["machine"]["feed_rate"] = 900
        assert store.get_resource("jobs", job["id"])["snapshot"] == frozen
        response = client.post(
            "/api/v1/jobs",
            json={"plan_id": plan["id"], "mode": "execute"},
            headers={"Idempotency-Key": "busy"},
        )
        assert response.status_code == 202
        assert response.json()["status"] == "queued"
    finally:
        release.set()
    assert wait(client, f"/api/v1/jobs/{job['id']}")["status"] == "succeeded"


def test_page_and_preview_guide_never_enter_gcode():
    a, _ = prepare_document(DocumentRequest(body="甲"))
    assert "stroke-dasharray" in a.svg
    assert a.strokes > 0 and a.can_print
    assert all("rect" not in line and "操作前检查" not in line for line in a.gcode)


def test_non_dataset_characters_block_writing():
    prepared, _ = prepare_document(DocumentRequest(body="甲A1!"))
    assert prepared.missing == ["A", "1", "!"]
    assert prepared.strokes > 0 and not prepared.can_print
