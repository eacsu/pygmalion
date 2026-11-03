"""公开契约、持久化接受与重试语义。所有任务使用模拟或替身设备。"""

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pygmalion import config
from pygmalion.api.app import create_app
from pygmalion.execution import repository as store
from pygmalion.schemas.canvas import CanvasDocument, TextBox


def document(**extra):
    return CanvasDocument(
        elements=[TextBox(id="text", text="甲乙")], **extra
    ).model_dump(mode="json")


def plan(client, **extra):
    result = client.post("/api/v1/plans", json=document(**extra))
    assert result.status_code == 201, result.text
    return result.json()


def wait(client, path):
    for _ in range(200):
        response = client.get(path)
        assert response.status_code == 200, response.text
        data = response.json()
        if data["status"] not in ("queued", "running", "cancelling"):
            return data
        time.sleep(0.01)
    raise AssertionError("执行没有结束")


def test_public_schema_is_complete_and_api_can_start_without_frontend(isolated_runtime):
    app = create_app(Path("/does-not-exist"), dry_run=True, serve_frontend=False)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/health").status_code == 404
        assert client.get("/api/admin/machine").status_code == 404
        schema = client.get("/openapi.json").json()
        for path, verbs in schema["paths"].items():
            for verb, operation in verbs.items():
                if verb not in ("get", "post", "patch", "delete"):
                    continue
                for status, response in operation["responses"].items():
                    assert response.get("content"), (path, verb, status)
                    assert all(
                        item.get("schema") for item in response["content"].values()
                    ), (path, verb, status)


def test_plan_is_immutable_reusable_and_submission_idempotent(client):
    prepared = plan(client)
    assert prepared["status"] == "ready" and prepared["expires_at"] is None
    before = client.get(prepared["preview_url"]).text
    data = {"plan_id": prepared["id"], "mode": "simulate"}
    headers = {"Idempotency-Key": "repeat"}
    first = client.post("/api/v1/jobs", json=data, headers=headers)
    assert first.status_code == 202, first.text
    original = wait(client, f"/api/v1/jobs/{first.json()['id']}")
    assert original["status"] == "succeeded"
    same = client.post("/api/v1/jobs", json=data, headers=headers)
    assert same.json()["id"] == original["id"]
    second = client.post(
        "/api/v1/jobs", json=data, headers={"Idempotency-Key": "another-copy"}
    )
    assert second.status_code == 202
    assert second.json()["id"] != original["id"]
    wait(client, f"/api/v1/jobs/{second.json()['id']}")
    config.CONFIG["machine"]["feed_rate"] = 5000
    assert client.get(prepared["preview_url"]).text == before
    assert client.get("/api/v1/plans/" + prepared["id"]).json() == prepared
    conflict = client.post(
        "/api/v1/jobs", json={**data, "mode": "execute"}, headers=headers
    )
    assert (
        conflict.status_code == 409
        and conflict.json()["error"]["code"] == "idempotency_conflict"
    )


def test_concurrent_retry_creates_one_job(client):
    prepared = plan(client)

    def submit(_):
        return client.post(
            "/api/v1/jobs",
            json={"plan_id": prepared["id"], "mode": "simulate"},
            headers={"Idempotency-Key": "concurrent"},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(submit, range(8)))
    assert all(response.status_code == 202 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1


def test_blocked_plan_and_changed_context_are_explicit(client):
    blocked = client.post(
        "/api/v1/plans",
        json=CanvasDocument(elements=[TextBox(id="t", text="不存在的字")]).model_dump(),
    ).json()
    assert blocked["status"] == "blocked" and blocked["diagnostics"]
    response = client.post(
        "/api/v1/jobs",
        json={"plan_id": blocked["id"], "mode": "simulate"},
        headers={"Idempotency-Key": "blocked"},
    )
    assert response.json()["error"]["code"] == "plan_blocked"
    prepared = plan(client)
    config.CONFIG["page"]["invert_x"] = False
    response = client.post(
        "/api/v1/jobs",
        json={"plan_id": prepared["id"], "mode": "simulate"},
        headers={"Idempotency-Key": "changed"},
    )
    assert response.json()["error"]["code"] == "execution_context_changed"


def test_config_cas_and_atomic_validation(client):
    response = client.get("/api/v1/settings/software")
    original = response.json()
    response = client.patch(
        "/api/v1/settings/software",
        json={"feed_rate": 8000, "z_on": 999},
        headers={"If-Match": original["etag"]},
    )
    assert response.status_code == 422
    assert client.get("/api/v1/settings/software").json() == original
    assert (
        client.patch("/api/v1/settings/software", json={"feed_rate": 8000}).status_code
        == 428
    )
    assert (
        client.patch(
            "/api/v1/settings/software",
            json={"feed_rate": 8000},
            headers={"If-Match": "stale"},
        ).status_code
        == 412
    )
    assert (
        client.patch(
            "/api/v1/settings/software",
            json={"feed_rate": 8000},
            headers={"If-Match": original["etag"]},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            "/api/v1/settings/software",
            json={"unknown": 1},
            headers={"If-Match": original["etag"]},
        ).status_code
        == 422
    )


def test_observation_and_simulation_never_open_serial(client, monkeypatch):
    runtime = client.app.state.services.execution

    def forbidden(*args, **kwargs):
        raise AssertionError("不应访问设备")

    monkeypatch.setattr(runtime.machine, "device_connection", forbidden)
    monkeypatch.setattr(runtime.machine, "read_anchor_position", forbidden)
    for _ in range(3):
        assert client.get("/api/v1/machine").status_code == 200
    with client.websocket_connect("/api/v1/events") as socket:
        assert socket.receive_json()["type"] == "machine.updated"
    assert runtime.owner is None
    prepared = plan(client, pen_anchor={"x_mm": 20, "y_mm": 20})
    response = client.post(
        "/api/v1/jobs",
        json={"plan_id": prepared["id"], "mode": "simulate"},
        headers={"Idempotency-Key": "virtual"},
    )
    assert (
        wait(client, f"/api/v1/jobs/{response.json()['id']}")["status"] == "succeeded"
    )
    assert (
        client.post(
            "/api/v1/jobs",
            json={"plan_id": prepared["id"], "mode": "execute"},
            headers={"Idempotency-Key": "real"},
        ).json()["error"]["code"]
        == "execution_disabled"
    )


def test_errors_have_request_id_and_validation_shape(client):
    for response in (
        client.post(
            "/api/v1/plans", content="{", headers={"Content-Type": "application/json"}
        ),
        client.post("/api/v1/plans", json={"unknown": 1}),
        client.get("/api/v1/jobs/9999"),
    ):
        body = response.json()
        assert body["request_id"] == response.headers["X-Request-ID"]
        assert body["error"]["code"] and body["error"]["retry_advice"]


def test_history_query_is_not_limited_to_latest_100(client):
    for number in range(130):
        store.create_resource(
            "jobs",
            {
                "id": 0,
                "mode": "simulate",
                "status": "succeeded",
                "created_at": store.now(),
            },
            {},
            str(number),
            str(number),
        )
    assert client.get("/api/v1/jobs/1").status_code == 200
    ids = []
    cursor = None
    while True:
        result = client.get(
            "/api/v1/jobs",
            params={"limit": 17, **({"before": cursor} if cursor else {})},
        ).json()
        ids.extend(item["id"] for item in result["data"])
        cursor = result["next_cursor"]
        if cursor is None:
            break
    assert len(ids) == len(set(ids)) == 130


def test_restart_preserves_keys_plans_and_never_replays(isolated_runtime):
    app = create_app(serve_frontend=False, dry_run=True)
    with TestClient(app) as client:
        prepared = plan(client)
        request = {"plan_id": prepared["id"], "mode": "simulate"}
        response = client.post(
            "/api/v1/jobs", json=request, headers={"Idempotency-Key": "restart"}
        )
        identifier = response.json()["id"]
        wait(client, f"/api/v1/jobs/{identifier}")
    with TestClient(create_app(serve_frontend=False, dry_run=True)) as client:
        assert client.get("/api/v1/plans/" + prepared["id"]).status_code == 200
        assert (
            client.post(
                "/api/v1/jobs", json=request, headers={"Idempotency-Key": "restart"}
            ).json()["id"]
            == identifier
        )


def test_operations_are_queryable_and_observers_do_not_take_control(
    client, monkeypatch
):
    runtime = client.app.state.services.execution
    calls = []
    monkeypatch.setattr(
        runtime.machine,
        "inspect",
        lambda **kwargs: (
            calls.append("inspect")
            or {
                "port": "/dev/ttyUSB0",
                "state": {"state": "Idle", "WPos": "0,0,0"},
                "firmware": ["test"],
            }
        ),
    )
    session = client.post(
        "/api/v1/machine/control-sessions", headers={"Idempotency-Key": "lease"}
    ).json()
    assert (
        client.post(
            "/api/v1/machine/control-sessions", headers={"Idempotency-Key": "lease"}
        ).json()["id"]
        == session["id"]
    )
    result = client.post(
        "/api/v1/machine/refresh",
        json={"session_id": session["id"]},
        headers={"Idempotency-Key": "refresh"},
    )
    assert result.status_code == 202, result.text
    operation = wait(client, "/api/v1/operations/" + result.json()["id"])
    assert operation["status"] == "succeeded"
    assert client.get("/api/v1/machine").json()["connected"]
    again = client.post(
        "/api/v1/machine/refresh",
        json={"session_id": session["id"]},
        headers={"Idempotency-Key": "refresh"},
    )
    assert again.json()["id"] == operation["id"] and calls == ["inspect"]
    assert (
        client.post(
            "/api/v1/serial-probes", json={}, headers={"Idempotency-Key": "busy"}
        ).status_code
        == 409
    )
    runtime.deadline = time.monotonic() - 1
    assert (
        client.post(
            "/api/v1/machine/control-sessions/" + session["id"] + "/renew", json={}
        ).status_code
        == 409
    )
    assert client.get("/api/v1/machine").status_code == 200


def test_anchor_binds_frozen_program_without_preparing_again(client, monkeypatch):
    runtime = client.app.state.services.execution
    runtime.dry_run = False
    prepared = plan(client, pen_anchor={"x_mm": 20, "y_mm": 20})
    captured = []
    monkeypatch.setattr(
        runtime.machine,
        "read_anchor_position",
        lambda: {"port": "/dev/ttyUSB0", "position": (-10, 10)},
    )

    def send(machine, program, **kwargs):
        captured.append((machine, program))
        kwargs["on_progress"](len(program), len(program))

    monkeypatch.setattr(runtime.machine, "send_program", send)
    result = client.post(
        "/api/v1/jobs",
        json={"plan_id": prepared["id"], "mode": "execute"},
        headers={"Idempotency-Key": "anchor"},
    )
    assert result.status_code == 202, result.text
    job = wait(client, "/api/v1/jobs/" + str(result.json()["id"]))
    assert job["status"] == "succeeded" and job["pen_position"] == [-10, 10]
    assert captured[0][0]["pen_anchor_position"] == [-10, 10] or captured[0][0][
        "pen_anchor_position"
    ] == (-10, 10)
    assert "G0 X-10.000 Y10.000" in captured[0][1]
    assert client.get("/api/v1/plans/" + prepared["id"]).json() == prepared


def test_emergency_does_not_wait_for_normal_device_admission(client, monkeypatch):
    runtime = client.app.state.services.execution
    observed = []
    monkeypatch.setattr(
        runtime.machine, "emergency_interrupt", lambda: observed.append("stop") or True
    )
    response = client.post("/api/v1/machine/emergency-stop")
    assert response.status_code == 202
    assert observed == ["stop"]
    assert response.json()["result"]["command_sent"] is True
    assert response.json()["result"]["stop_confirmed"] is False
    assert response.json()["status"] == "interrupted"


def test_driver_work_position_handles_units_offsets_and_missing_evidence(monkeypatch):
    from pygmalion.machine import grbl

    link = grbl.GrblLink.__new__(grbl.GrblLink)
    monkeypatch.setattr(grbl.time, "sleep", lambda seconds: None)
    link.query = lambda *args, **kwargs: ["$13=0"]
    states = iter(
        [
            {"state": "Idle", "MPos": "10,20,0"},
            {"state": "Idle", "MPos": "10,20,0", "WCO": "2,3,0"},
        ]
    )
    link.status = lambda: next(states)
    assert link.work_position() == (8, 17)
    link.query = lambda *args, **kwargs: ["$13=1"]
    link.status = lambda: {"state": "Idle", "WPos": "1,2,0"}
    assert link.work_position() == pytest.approx((25.4, 50.8))
    link.status = lambda: {"state": "Idle", "MPos": "1,2,0"}
    with pytest.raises(grbl.GrblError, match="偏移"):
        link.work_position()


def test_running_records_recover_conservatively_without_replay(client):
    store.create_resource(
        "jobs",
        {"id": 0, "mode": "execute", "status": "running", "created_at": store.now()},
        {},
        "crash",
        "crash",
    )
    store.initialize()
    job = client.get("/api/v1/jobs/1").json()
    assert job["status"] == "interrupted"
    assert job["error"]["code"] == "service_restarted"


def test_session_retry_after_restart_does_not_revive_control(isolated_runtime):
    with TestClient(create_app(serve_frontend=False, dry_run=True)) as client:
        original = client.post(
            "/api/v1/machine/control-sessions",
            json={},
            headers={"Idempotency-Key": "session-retry"},
        ).json()
        assert original["status"] == "active"
    with TestClient(create_app(serve_frontend=False, dry_run=True)) as client:
        retried = client.post(
            "/api/v1/machine/control-sessions",
            json={},
            headers={"Idempotency-Key": "session-retry"},
        )
        assert retried.status_code == 409
        assert retried.json()["error"]["code"] == "session_expired"
        assert client.app.state.services.execution.owner is None


@pytest.mark.parametrize(
    "rejection, expected", [(True, "failed"), (False, "interrupted")]
)
def test_firmware_partial_results_keep_known_and_unknown_items(
    client, monkeypatch, rejection, expected
):
    from contextlib import contextmanager

    from pygmalion.machine import grbl

    runtime = client.app.state.services.execution
    calls = []
    backup = grbl.BACKUP_DIR / "grbl-settings-test.txt"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text("backup")

    class Link:
        def backup(self, **kwargs):
            return backup

        def write_settings(self, changes, **kwargs):
            calls.append(changes)
            if len(calls) == 2:
                raise (
                    grbl.CommandRejected("error:3")
                    if rejection
                    else OSError("response lost")
                )

    @contextmanager
    def connection(*args, **kwargs):
        yield Link()

    monkeypatch.setattr(runtime.machine, "device_connection", connection)
    session = client.post(
        "/api/v1/machine/control-sessions",
        json={},
        headers={"Idempotency-Key": "firmware-session"},
    ).json()["id"]
    preview = client.post(
        "/api/v1/machine/settings/previews",
        json={"changes": {"$110": 4000, "$111": 4000, "$112": 5000}},
    )
    assert preview.status_code == 201, preview.text
    response = client.post(
        f"/api/v1/machine/settings/previews/{preview.json()['id']}/apply",
        json={"session_id": session},
        headers={"Idempotency-Key": "apply-once"},
    )
    assert response.status_code == 202, response.text
    result = wait(client, "/api/v1/operations/" + response.json()["id"])
    assert result["status"] == expected
    assert result["result"]["applied"] == ["$110"]
    assert result["result"]["failed" if rejection else "unknown"] == ["$111"]
    assert result["result"]["not_applied"] == ["$112"]
    # 重试已有操作不会重新写控制板，也不会因当前上下文变化丢失结果。
    assert (
        client.post(
            f"/api/v1/machine/settings/previews/{preview.json()['id']}/apply",
            json={"session_id": session},
            headers={"Idempotency-Key": "apply-once"},
        ).json()["id"]
        == result["id"]
    )
    assert len(calls) == 2


def test_execution_retains_verified_connection_and_rejects_connection_loss(monkeypatch):
    from pygmalion.machine import grbl
    from pygmalion.machine.controller import DeviceController
    from pygmalion.machine.errors import ExecutionRejected

    links = []
    sent = []

    class Link:
        def __init__(self, *args, **kwargs):
            self.port = "/dev/ttyUSB0"
            self.is_open = True
            links.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.is_open = False

        def work_position(self):
            return (10.0, 20.0)

        def status(self):
            return {"state": "Idle"}

        def run_program(self, program, **kwargs):
            sent.extend(program)

        def wait_idle(self, **kwargs):
            pass

    monkeypatch.setattr(grbl, "GrblLink", Link)
    monkeypatch.setattr(grbl, "ensure_backup_today", lambda link, **kwargs: None)
    controller = DeviceController()
    reference = controller.read_anchor_position()
    machine = {
        **config.CONFIG["machine"],
        "port": reference["port"],
        "execution_position": reference["position"],
    }
    controller.send_program(
        machine,
        ["G21", "G0 X10 Y20"],
        submission_id=1,
        on_progress=lambda *args: None,
        cancelled=lambda: False,
    )
    assert len(links) == 1 and sent == ["G21", "G0 X10 Y20"]
    controller.stop()
    with pytest.raises(ExecutionRejected, match="连接已改变"):
        controller.send_program(
            machine,
            ["G0 X1 Y1"],
            submission_id=2,
            on_progress=lambda *args: None,
            cancelled=lambda: False,
        )
    assert len(links) == 1


def test_cancel_cleanup_error_is_not_reported_as_confirmed_cancellation():
    from pygmalion.machine import grbl

    link = grbl.GrblLink("COM99", 115200)

    def lost(**kwargs):
        raise grbl.GrblError("connection lost during cleanup")

    link.wait_idle = lost
    with pytest.raises(grbl.GrblError, match="cleanup"):
        link._finish_cancel(pen_up_z=0, idx=2, total=10)


def test_unexpected_errors_keep_public_envelope_and_request_id(client, monkeypatch):
    runtime = client.app.state.services.execution

    def fail(*args):
        raise RuntimeError("private internal details")

    monkeypatch.setattr(runtime, "prepare", fail)
    transport = TestClient(client.app, raise_server_exceptions=False)
    try:
        response = transport.post("/api/v1/plans", json=document())
    finally:
        transport.close()
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert "private internal details" not in response.text


@pytest.mark.parametrize("state", ["Hold:0", "Hold:1", "Alarm"])
def test_anchor_after_emergency_explains_explicit_recovery(state):
    from pygmalion.machine import grbl

    link = grbl.GrblLink.__new__(grbl.GrblLink)
    link.status = lambda: {"state": state}
    link.query = lambda *args, **kwargs: pytest.fail("未恢复 Idle 时不得继续读取定位")
    with pytest.raises(grbl.GrblError) as error:
        link.work_position()
    assert state in str(error.value)
    assert "解除卡死 / 恢复" in str(error.value)
    assert "不会自动续写" in str(error.value)


def test_anchor_rejects_motion_that_starts_while_reading_offsets(monkeypatch):
    from pygmalion.machine import grbl

    link = grbl.GrblLink.__new__(grbl.GrblLink)
    monkeypatch.setattr(grbl.time, "sleep", lambda _: None)
    states = iter(
        [{"state": "Idle", "MPos": "1,2,0"}, {"state": "Run", "WPos": "5,6,0"}]
    )
    link.status = lambda: next(states)
    link.query = lambda *args, **kwargs: ["$13=0"]
    with pytest.raises(grbl.GrblError, match="Run.*仍在运动"):
        link.work_position()
