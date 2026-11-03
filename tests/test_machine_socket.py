import threading
from datetime import datetime

import pytest

from pygmalion import config
from pygmalion.machine import grbl
from tests.test_public_api import wait


@pytest.fixture
def fake_machine(monkeypatch, isolated_runtime):
    links = []
    programs = []
    backups = []
    started = threading.Event()
    release = threading.Event()
    release.set()
    config.CONFIG["machine"]["port"] = "COM17"

    class Link:
        def __init__(self, port, baud, **kwargs):
            self.port, self.baud = port, baud
            self.is_open = False
            self.backed_up = False
            links.append(self)

        def __enter__(self):
            self.is_open = True
            return self

        def __exit__(self, *args):
            self.is_open = False

        def query(self, command, **kwargs):
            return ["[VER:1.1:test]"]

        def status(self):
            return {"state": "Idle", "MPos": f"{len(programs)},0,0"}

        def mark_backed_up(self):
            self.backed_up = True

        def backup(self, reason):
            backups.append(reason)
            path = grbl.BACKUP_DIR / "grbl-settings-latest.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                datetime.now().astimezone().strftime("%Y-%m-%d"), encoding="utf-8"
            )
            self.mark_backed_up()
            return path

        def run_program(self, program):
            assert self.backed_up
            programs.append(program)
            started.set()
            assert release.wait(5), "test command not released"

        def wait_idle(self, **kwargs):
            return self.status()

        def send(self, command):
            assert self.backed_up
            programs.append([command])

    monkeypatch.setattr(grbl, "GrblLink", Link)
    return links, programs, backups, started, release


def lease(client):
    response = client.post(
        "/api/v1/machine/control-sessions", headers={"Idempotency-Key": "controller"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def command(client, session, key, **payload):
    response = client.post(
        "/api/v1/machine/commands",
        json={"session_id": session, **payload},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


def test_commands_order_rapid_directions_reuse_serial_and_backup(client, fake_machine):
    links, programs, backups, _, _ = fake_machine
    session = lease(client)
    identifiers = [
        command(
            client, session, str(index), type="jog", axis=axis, distance_mm=distance
        )
        for index, (axis, distance) in enumerate([("x", 1), ("y", -1), ("x", -1)])
    ]
    for identifier in identifiers:
        assert wait(client, "/api/v1/operations/" + identifier)["status"] == "succeeded"
    assert len(links) == 1 and len(backups) == 1
    assert [program[1] for program in programs] == [
        "G1 X1 F3000",
        "G1 Y-1 F3000",
        "G1 X-1 F3000",
    ]
    client.delete("/api/v1/machine/control-sessions/" + session)
    assert not links[0].is_open


def test_pending_operations_are_bounded(client, fake_machine):
    _, programs, _, started, release = fake_machine
    session = lease(client)
    release.clear()
    identifiers = []
    try:
        for index in range(4):
            identifiers.append(
                command(
                    client, session, str(index), type="jog", axis="x", distance_mm=1
                )
            )
        assert started.wait(2)
        response = client.post(
            "/api/v1/machine/commands",
            json={"type": "jog", "axis": "x", "distance_mm": 1, "session_id": session},
            headers={"Idempotency-Key": "overflow"},
        )
        assert response.status_code == 409
    finally:
        release.set()
    for identifier in identifiers:
        wait(client, "/api/v1/operations/" + identifier)
    assert len(programs) == 4


def test_releasing_session_drops_unsent_motion(client, fake_machine):
    _links, programs, _, started, release = fake_machine
    session = lease(client)
    release.clear()
    first = command(client, session, "first", type="jog", axis="x", distance_mm=1)
    try:
        assert started.wait(2)
        second = command(client, session, "second", type="jog", axis="y", distance_mm=1)
        response = client.delete("/api/v1/machine/control-sessions/" + session)
        assert response.json()["status"] == "closing"
        assert (
            client.post(
                "/api/v1/serial-probes", json={}, headers={"Idempotency-Key": "probe"}
            ).status_code
            == 409
        )
    finally:
        release.set()
    wait(client, "/api/v1/operations/" + first)
    assert wait(client, "/api/v1/operations/" + second)["status"] == "cancelled"
    assert len(programs) == 1


def test_second_controller_is_refused_and_observer_is_allowed(client, fake_machine):
    lease(client)
    assert (
        client.post(
            "/api/v1/machine/control-sessions", headers={"Idempotency-Key": "other"}
        ).status_code
        == 409
    )
    with client.websocket_connect("/api/v1/events") as socket:
        assert socket.receive_json()["type"] == "machine.updated"
    assert not fake_machine[0]


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "jog", "axis": "x", "distance_mm": 0},
        {"type": "jog", "axis": "z", "distance_mm": 1},
        {"type": "jog", "axis": "x", "distance_mm": 61},
        {"type": "jog", "axis": "x", "distance_mm": "NaN"},
    ],
)
def test_invalid_command_never_opens_machine(client, fake_machine, payload):
    session = lease(client)
    response = client.post(
        "/api/v1/machine/commands",
        json={"session_id": session, **payload},
        headers={"Idempotency-Key": "invalid"},
    )
    assert response.status_code == 422
    assert not fake_machine[0]


def test_duplicate_motion_key_does_not_repeat(client, fake_machine):
    session = lease(client)
    original = command(client, session, "same", type="jog", axis="x", distance_mm=1)
    wait(client, "/api/v1/operations/" + original)
    assert (
        command(client, session, "same", type="jog", axis="x", distance_mm=1)
        == original
    )
    assert len(fake_machine[1]) == 1
    response = client.post(
        "/api/v1/machine/commands",
        json={"session_id": session, "type": "jog", "axis": "y", "distance_mm": 1},
        headers={"Idempotency-Key": "same"},
    )
    assert response.status_code == 409


def test_serial_failure_closes_link_and_cancels_following_commands(
    client, fake_machine, monkeypatch
):
    links, programs, _, _, _ = fake_machine
    session = lease(client)
    entered, release = threading.Event(), threading.Event()

    def fail_program(link, program):
        entered.set()
        assert release.wait(3)
        raise OSError("connection lost")

    monkeypatch.setattr(grbl.GrblLink, "run_program", fail_program)
    first = command(client, session, "fail", type="jog", axis="x", distance_mm=1)
    try:
        assert entered.wait(2)
        second = command(
            client, session, "pending", type="jog", axis="y", distance_mm=1
        )
    finally:
        release.set()
    assert wait(client, "/api/v1/operations/" + first)["status"] == "interrupted"
    assert wait(client, "/api/v1/operations/" + second)["status"] == "cancelled"
    assert not links[0].is_open and not programs


def test_backup_failure_prevents_motion(client, fake_machine, monkeypatch):
    session = lease(client)

    def fail(*args, **kwargs):
        raise OSError("backup failed")

    monkeypatch.setattr(grbl, "ensure_backup_today", fail)
    operation = command(
        client, session, "backup-failure", type="jog", axis="x", distance_mm=1
    )
    result = wait(client, "/api/v1/operations/" + operation)
    assert result["status"] in ("failed", "interrupted")
    assert not fake_machine[1]


def test_idle_session_poll_pushes_coordinates_without_extra_refresh(
    client, fake_machine
):
    session = lease(client)
    response = client.post(
        "/api/v1/machine/refresh",
        json={"session_id": session},
        headers={"Idempotency-Key": "read"},
    )
    wait(client, "/api/v1/operations/" + response.json()["id"])
    fake_machine[1].append(["external-test-move"])
    with client.websocket_connect("/api/v1/events") as socket:
        for _ in range(20):
            event = socket.receive_json()
            if (
                event["type"] == "machine.updated"
                and event["data"]["state"].get("MPos") == "1,0,0"
            ):
                break
        else:
            raise AssertionError("未推送采样坐标")
