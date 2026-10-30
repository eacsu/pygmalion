"""工作区生命周期、已确认取消、硬件写入闸门与历史迁移。"""

import json
import threading

import pytest

from pygmalion.execution import repository as store
from pygmalion.machine.errors import ExecutionCancelled
from tests.test_public_api import plan, wait


def test_removed_legacy_routes_never_fall_back_to_frontend(client):
    for path in (
        "/api/submit",
        "/api/admin/jobs",
        "/api/admin/machine",
        "/api/workbench/preview",
        "/api/my/1",
    ):
        assert client.get(path, headers={"Accept": "text/html"}).status_code == 404
    assert client.get("/api/v1/fonts").status_code == 200


def test_real_job_waits_for_idle_before_succeeded(client, monkeypatch):
    runtime = client.app.state.services.execution
    runtime.dry_run = False
    sent, release = threading.Event(), threading.Event()

    def send(machine, program, **kwargs):
        kwargs["on_progress"](len(program), len(program))
        sent.set()
        assert release.wait(3)

    monkeypatch.setattr(
        runtime.machine,
        "read_anchor_position",
        lambda: {"port": "COM99", "position": (0.0, 0.0)},
    )
    monkeypatch.setattr(runtime.machine, "send_program", send)
    prepared = plan(client)
    job = client.post(
        "/api/v1/jobs",
        json={"plan_id": prepared["id"], "mode": "execute"},
        headers={"Idempotency-Key": "wait-idle"},
    ).json()
    try:
        assert sent.wait(2)
        pending = client.get(f"/api/v1/jobs/{job['id']}").json()
        assert pending["percent"] == 100 and pending["status"] == "running"
    finally:
        release.set()
    assert wait(client, f"/api/v1/jobs/{job['id']}")["status"] == "succeeded"


def test_cancel_is_not_complete_before_confirmed_stop(client, monkeypatch):
    runtime = client.app.state.services.execution
    runtime.dry_run = False
    entered, release = threading.Event(), threading.Event()

    def send(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        raise ExecutionCancelled("已确认停稳并抬笔")

    monkeypatch.setattr(
        runtime.machine,
        "read_anchor_position",
        lambda: {"port": "COM99", "position": (0.0, 0.0)},
    )
    monkeypatch.setattr(runtime.machine, "send_program", send)
    prepared = plan(client)
    job = client.post(
        "/api/v1/jobs",
        json={"plan_id": prepared["id"], "mode": "execute"},
        headers={"Idempotency-Key": "cancel"},
    ).json()
    try:
        assert entered.wait(2)
        response = client.post(f"/api/v1/jobs/{job['id']}/cancel", json={})
        assert response.json()["status"] == "cancelling"
        assert (
            client.post(f"/api/v1/jobs/{job['id']}/cancel", json={}).json()["status"]
            == "cancelling"
        )
    finally:
        release.set()
    assert wait(client, f"/api/v1/jobs/{job['id']}")["status"] == "cancelled"
    assert (
        client.post(f"/api/v1/jobs/{job['id']}/cancel", json={}).json()["status"]
        == "cancelled"
    )


def test_communication_loss_after_sending_is_interrupted(client, monkeypatch):
    runtime = client.app.state.services.execution
    runtime.dry_run = False

    def send(*args, **kwargs):
        raise OSError("lost response")

    monkeypatch.setattr(
        runtime.machine,
        "read_anchor_position",
        lambda: {"port": "COM99", "position": (0.0, 0.0)},
    )
    monkeypatch.setattr(runtime.machine, "send_program", send)
    prepared = plan(client)
    response = client.post(
        "/api/v1/jobs",
        json={"plan_id": prepared["id"], "mode": "execute"},
        headers={"Idempotency-Key": "lost"},
    )
    result = wait(client, f"/api/v1/jobs/{response.json()['id']}")
    assert result["status"] == "interrupted"
    assert result["error"]["retry_advice"] == "query_status"


def test_cancel_queued_job_never_sends(client, monkeypatch):
    runtime = client.app.state.services.execution
    queued = []
    original = runtime.jobs.put
    monkeypatch.setattr(runtime.jobs, "put", queued.append)
    prepared = plan(client)
    response = client.post(
        "/api/v1/jobs",
        json={"plan_id": prepared["id"], "mode": "simulate"},
        headers={"Idempotency-Key": "queued"},
    )
    identifier = response.json()["id"]
    assert (
        client.post(f"/api/v1/jobs/{identifier}/cancel", json={}).json()["status"]
        == "cancelled"
    )
    monkeypatch.setattr(runtime.jobs, "put", original)
    original(identifier)
    assert wait(client, f"/api/v1/jobs/{identifier}")["sent"] == 0


def test_grbl_preview_is_offline_and_rejects_injection(client, monkeypatch):
    runtime = client.app.state.services.execution

    def forbidden(*args, **kwargs):
        raise AssertionError("离线预览不应打开设备")

    monkeypatch.setattr(runtime.machine, "device_connection", forbidden)
    response = client.post(
        "/api/v1/machine/settings/previews", json={"changes": {"$110": 4000}}
    )
    assert response.status_code == 201
    assert response.json()["commands"] == ["$110=4000"]
    for changes in ({"$110\n$H": 4000}, {"$110": "4000\n$H"}):
        assert (
            client.post(
                "/api/v1/machine/settings/previews", json={"changes": changes}
            ).status_code
            == 422
        )


def test_only_one_runtime_can_own_a_database(isolated_runtime):
    from fastapi.testclient import TestClient

    from pygmalion.api.app import create_app

    with (
        TestClient(create_app(serve_frontend=False, dry_run=True)),
        pytest.raises(RuntimeError, match="第二个执行器"),
        TestClient(create_app(serve_frontend=False, dry_run=True)),
    ):
        pass


def test_old_history_migration_keeps_ids_without_resuming(isolated_runtime):
    from pygmalion.storage import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO print_jobs(id,submission_id,status,created_at,snapshot) VALUES(200,1,'printing','2025-01-01','{}')"
        )
    store.initialize()
    assert (
        json.loads(store.get_resource("jobs", 200)["data"])["status"] == "interrupted"
    )
    store.initialize()
    assert len(store.list_jobs()[0]) == 1
