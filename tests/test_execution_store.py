"""资源持久化与去重的事务边界。"""

import json

import pytest

from pygmalion.execution import repository as store
from pygmalion.plans.service import create_plan
from pygmalion.schemas.canvas import CanvasDocument, TextBox


def test_durable_plan_keeps_program_and_preview_together(isolated_runtime):
    store.initialize()
    result = create_plan(CanvasDocument(elements=[TextBox(id="t", text="甲")]))
    stored = store.get_plan(result.id)
    assert result.status == "ready"
    assert stored["svg"] and stored["program"]
    assert stored["plan"]["document"]["elements"][0]["text"] == "甲"
    store.initialize()
    assert store.get_plan(result.id) == stored


def test_acceptance_and_key_share_a_transaction(isolated_runtime):
    store.initialize()
    payload = {
        "id": 0,
        "status": "queued",
        "created_at": store.now(),
        "mode": "simulate",
    }
    identifier, created = store.create_resource(
        "jobs", payload, {"program": ["G21"]}, "same", "digest"
    )
    assert created
    again, created = store.create_resource("jobs", dict(payload), {}, "same", "digest")
    assert again == identifier and not created
    with pytest.raises(store.Conflict):
        store.create_resource("jobs", dict(payload), {}, "same", "different")
    row = store.get_resource("jobs", identifier)
    assert json.loads(row["snapshot"]) == {"program": ["G21"]}
    assert len(store.list_jobs()[0]) == 1


def test_schema_accepts_anchor_outside_reference_paper():
    doc = CanvasDocument(paper="A5", pen_anchor={"x_mm": -200.0, "y_mm": 500.0})
    assert doc.pen_anchor.x_mm == -200.0
