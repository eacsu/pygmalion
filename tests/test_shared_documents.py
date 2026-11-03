import json
import threading

from pygmalion.execution import repository as store
from pygmalion.schemas.canvas import CanvasDocument, TextBox
from tests.test_public_api import wait


def test_shared_documents_survive_new_client_and_conflicts_are_rejected(client):
    doc = CanvasDocument(
        name="共享文档", elements=[TextBox(id="title", text="甲")]
    ).model_dump()
    created = client.post(
        "/api/v1/documents", json=doc, headers={"Idempotency-Key": "first"}
    )
    assert created.status_code == 201
    value = created.json()
    assert (
        client.post(
            "/api/v1/documents", json=doc, headers={"Idempotency-Key": "first"}
        ).json()["id"]
        == value["id"]
    )
    url = "/api/v1/documents/" + value["id"]
    assert client.get(url).json()["document"] == doc
    doc["name"] = "另一个客户端的排版"
    saved = client.put(url, json=doc, headers={"If-Match": created.headers["ETag"]})
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    assert (
        client.put(
            url, json={**doc, "name": "过期客户端"}, headers={"If-Match": '"1"'}
        ).status_code
        == 412
    )
    assert client.put(url, json=doc).status_code == 428
    assert client.get(url).json()["document"]["name"] == "另一个客户端的排版"
    listing = client.get("/api/v1/documents").json()["data"]
    assert listing[0]["name"] == doc["name"]
    assert "document" not in listing[0]
    assert client.get("/api/v1/documents/nonexistent").status_code == 404


def test_multiple_clients_can_queue_frozen_jobs_without_reading_position_while_busy(
    client, monkeypatch
):
    runtime = client.app.state.services.execution
    runtime.dry_run = False
    entered, release = threading.Event(), threading.Event()
    calls, reads = [], []

    def read():
        reads.append(len(reads))
        return {"port": "test", "position": (len(reads), 0)}

    def send(machine, program, **kwargs):
        calls.append((kwargs["submission_id"], machine, list(program)))
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        kwargs["on_progress"](10, 10)

    monkeypatch.setattr(runtime.machine, "read_anchor_position", read)
    monkeypatch.setattr(runtime.machine, "send_program", send)
    doc = CanvasDocument(
        elements=[TextBox(id="t", text="甲")], pen_anchor={"x_mm": 20, "y_mm": 20}
    ).model_dump()
    plan = client.post("/api/v1/plans", json=doc).json()
    body = {"plan_id": plan["id"], "mode": "execute"}
    try:
        first = client.post(
            "/api/v1/jobs", json=body, headers={"Idempotency-Key": "client-a"}
        ).json()
        assert entered.wait(2)
        second = client.post(
            "/api/v1/jobs", json=body, headers={"Idempotency-Key": "client-b"}
        )
        assert second.status_code == 202 and second.json()["status"] == "queued"
        assert len(reads) == 1
        third = client.post(
            "/api/v1/jobs", json=body, headers={"Idempotency-Key": "client-c"}
        ).json()
        queue = client.get("/api/v1/queue").json()
        assert queue["running"]["id"] == first["id"]
        assert [j["id"] for j in queue["queued"]] == [second.json()["id"], third["id"]]
        assert queue["queued_total"] == 2
        assert (
            client.post(f"/api/v1/jobs/{third['id']}/cancel").json()["status"]
            == "cancelled"
        )
        assert (
            client.post(
                "/api/v1/jobs", json=body, headers={"Idempotency-Key": "client-b"}
            ).json()["id"]
            == second.json()["id"]
        )
    finally:
        release.set()
    assert wait(client, f"/api/v1/jobs/{second.json()['id']}")["status"] == "succeeded"
    assert [c[0] for c in calls] == [first["id"], second.json()["id"]]
    assert len(reads) == 2
    snapshot = json.loads(store.get_resource("jobs", second.json()["id"])["snapshot"])
    assert snapshot["position_pending"] is False
    assert snapshot["machine"]["execution_position"] == [2, 0]
    assert client.get("/api/v1/queue").json()["queued_total"] == 0


def test_interrupted_machine_does_not_start_next_queued_job(client, monkeypatch):
    runtime = client.app.state.services.execution
    runtime.dry_run = False
    entered, release = threading.Event(), threading.Event()
    calls = []

    def send(*args, **kwargs):
        calls.append(kwargs["submission_id"])
        entered.set()
        assert release.wait(5)
        raise RuntimeError("connection lost after sending")

    monkeypatch.setattr(
        runtime.machine,
        "read_anchor_position",
        lambda: {"port": "test", "position": (0, 0)},
    )
    monkeypatch.setattr(runtime.machine, "send_program", send)
    plan = client.post(
        "/api/v1/plans",
        json=CanvasDocument(elements=[TextBox(id="t", text="甲")]).model_dump(),
    ).json()
    body = {"plan_id": plan["id"], "mode": "execute"}
    try:
        first = client.post(
            "/api/v1/jobs", json=body, headers={"Idempotency-Key": "interrupt-a"}
        ).json()
        assert entered.wait(2)
        second = client.post(
            "/api/v1/jobs", json=body, headers={"Idempotency-Key": "interrupt-b"}
        ).json()
        assert second["status"] == "queued"
    finally:
        release.set()
    assert wait(client, f"/api/v1/jobs/{first['id']}")["status"] == "interrupted"
    result = wait(client, f"/api/v1/jobs/{second['id']}")
    assert result["status"] == "failed"
    assert result["error"]["code"] == "emergency_active"
    assert calls == [first["id"]]
