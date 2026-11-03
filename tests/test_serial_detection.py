from types import SimpleNamespace

import pytest

from pygmalion import config
from pygmalion.machine import grbl


def port(device, hwid="USB VID:PID=1A86:7523"):
    return {
        "device": device,
        "description": device,
        "hwid": hwid,
        "vid": None,
        "pid": None,
    }


@pytest.fixture
def serial_probe(monkeypatch):
    clock = SimpleNamespace(now=0.0)

    def sleep(seconds):
        clock.now += seconds

    monkeypatch.setattr(
        grbl, "time", SimpleNamespace(sleep=sleep, monotonic=lambda: clock.now)
    )
    monkeypatch.setattr(grbl, "serial_ports", lambda: [port("COM17")])
    opened = []

    class Serial:
        def __init__(self, device, baud, **kwargs):
            self.device = device
            self.is_open = True
            self.written = []
            self.responses = []
            opened.append(self)

        def write(self, payload):
            self.written.append(payload)
            self.responses.extend(reply(len(self.written)))

        def readline(self):
            sleep(0.15)
            return self.responses.pop(0) if self.responses else b""

        def close(self):
            self.is_open = False

    reply = lambda count: [b"[VER:1.1:]\n", b"ok\n"]

    def set_reply(callback):
        nonlocal reply
        reply = callback

    monkeypatch.setattr(grbl.serial, "Serial", Serial)
    return opened, set_reply


@pytest.mark.parametrize("prefix", [[], [b"ok\n"], [b"ok\n", b"ok\n"]])
def test_probe_waits_for_version_despite_stale_ack(serial_probe, prefix):
    opened, set_reply = serial_probe
    set_reply(lambda count: prefix + [b"[VER:1.1:]\n", b"ok\n"])
    result = grbl.probe_grbl_ports()[0]
    assert result["grbl"] and result["firmware"] == "[VER:1.1:]"
    assert opened[0].written == [b"$I\n"]
    assert not opened[0].is_open


def test_probe_retries_query_if_board_is_still_booting(serial_probe):
    opened, set_reply = serial_probe
    set_reply(
        lambda count: [] if count == 1 else [b"Grbl 1.1h ['$' for help]\n", b"ok\n"]
    )
    assert grbl.probe_grbl_ports()[0]["grbl"]
    assert opened[0].written == [b"$I\n", b"$I\n"]
    assert not opened[0].is_open


@pytest.mark.parametrize("response,reachable", [([], False), ([b"ok\n"], True)])
def test_probe_without_version_times_out_and_closes(serial_probe, response, reachable):
    opened, set_reply = serial_probe
    set_reply(lambda count: response)
    result = grbl.probe_grbl_ports()[0]
    assert not result["grbl"] and result["reachable"] is reachable
    assert result["error"] and result["elapsed_ms"] <= 3500
    assert len(opened[0].written) == 2 and not opened[0].is_open


def test_auto_skips_bluetooth_but_explicit_probe_can_select_it(
    serial_probe, monkeypatch
):
    opened, _ = serial_probe
    monkeypatch.setattr(
        grbl, "serial_ports", lambda: [port("COM12", "BTHENUM\\device"), port("COM17")]
    )
    results = grbl.probe_grbl_ports()
    assert results[0]["skipped"] and results[1]["grbl"]
    assert [ser.device for ser in opened] == ["COM17"]
    assert grbl.probe_grbl_ports(devices=["com12"])[0]["grbl"]
    assert opened[-1].device == "COM12"


def test_probe_open_failure_reports_device_and_continues(serial_probe, monkeypatch):
    opened, _ = serial_probe
    constructor = grbl.serial.Serial

    def serial(device, *args, **kwargs):
        if device == "COM16":
            raise grbl.serial.SerialException("Access denied")
        return constructor(device, *args, **kwargs)

    monkeypatch.setattr(grbl.serial, "Serial", serial)
    monkeypatch.setattr(grbl, "serial_ports", lambda: [port("COM16"), port("COM17")])
    results = grbl.probe_grbl_ports()
    assert "Access denied" in results[0]["error"] and results[1]["grbl"]
    assert not opened[0].is_open


def test_detection_api_saves_verified_port(client, serial_probe):
    from tests.test_public_api import wait

    response = client.post(
        "/api/v1/serial-probes", json={}, headers={"Idempotency-Key": "probe"}
    )
    assert response.status_code == 202
    operation = wait(client, "/api/v1/operations/" + response.json()["id"])
    assert operation["result"]["ports"][0]["grbl"]
    assert config.CONFIG["machine"]["port"] == "auto"


@pytest.mark.parametrize(
    "value,expected",
    [
        (" com8 ", "COM8"),
        ("AUTO", "auto"),
        ("/dev/ttyUSB0", "/dev/ttyUSB0"),
        ("/dev/ttyACM0", "/dev/ttyACM0"),
        ("/dev/ttyS0", "/dev/ttyS0"),
        ("/dev/cu.usbserial-A12", "/dev/cu.usbserial-A12"),
        (
            "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0",
            "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0",
        ),
        (
            "/dev/serial/by-path/pci-0000:00:14.0-usb-0:1:1.0-port0",
            "/dev/serial/by-path/pci-0000:00:14.0-usb-0:1:1.0-port0",
        ),
    ],
)
def test_save_serial_port_preserves_platform_names(
    client, serial_probe, value, expected
):
    opened, _ = serial_probe
    response = client.patch(
        "/api/v1/machine/connection",
        json={"port": value},
        headers={"If-Match": client.get("/api/v1/machine/connection").json()["etag"]},
    )
    assert response.status_code == 200
    assert (
        response.json()["values"]["port"]
        == config.CONFIG["machine"]["port"]
        == expected
    )
    assert opened == []  # 保存选择不能打开串口或发送指令。


@pytest.mark.parametrize(
    "value",
    [
        "",
        "COM0",
        "COMfoo",
        "/tmp/port",
        "/dev/ttyUSB0/../other",
        "socket://localhost:1234",
    ],
)
def test_save_serial_port_rejects_invalid_names(client, serial_probe, value):
    response = client.patch(
        "/api/v1/machine/connection",
        json={"port": value},
        headers={"If-Match": client.get("/api/v1/machine/connection").json()["etag"]},
    )
    assert response.status_code == 422
    assert config.CONFIG["machine"]["port"] == "auto"


def test_save_serial_port_accepts_system_enumerated_device(
    client, serial_probe, monkeypatch
):
    monkeypatch.setattr(grbl, "serial_ports", lambda: [port("/dev/custom-UART")])
    response = client.patch(
        "/api/v1/machine/connection",
        json={"port": "/dev/custom-UART"},
        headers={"If-Match": client.get("/api/v1/machine/connection").json()["etag"]},
    )
    assert response.status_code == 200
    assert config.CONFIG["machine"]["port"] == "/dev/custom-UART"


def test_detection_api_does_not_guess_between_two_machines(
    client, serial_probe, monkeypatch
):
    from tests.test_public_api import wait

    monkeypatch.setattr(grbl, "serial_ports", lambda: [port("COM17"), port("COM18")])
    response = client.post(
        "/api/v1/serial-probes", json={}, headers={"Idempotency-Key": "two"}
    )
    result = wait(client, "/api/v1/operations/" + response.json()["id"])
    assert len([p for p in result["result"]["ports"] if p["grbl"]]) == 2
    assert config.CONFIG["machine"]["port"] == "auto"


def test_detection_api_includes_port_failure_in_message(client, serial_probe):
    from tests.test_public_api import wait

    _, set_reply = serial_probe
    set_reply(lambda count: [b"ok\n"])
    response = client.post(
        "/api/v1/serial-probes", json={}, headers={"Idempotency-Key": "failed-probe"}
    )
    result = wait(client, "/api/v1/operations/" + response.json()["id"])["result"][
        "ports"
    ][0]
    assert result["device"] == "COM17"
    assert "未返回 GRBL 版本信息" in result["error"]
    assert config.CONFIG["machine"]["port"] == "auto"


def test_detection_api_never_opens_port_during_writing(client, serial_probe):
    opened, _ = serial_probe
    runtime = client.app.state.services.execution
    runtime.owner = ("job", 123)
    try:
        response = client.post(
            "/api/v1/serial-probes", json={}, headers={"Idempotency-Key": "busy"}
        )
        assert response.status_code == 409 and not opened
    finally:
        runtime.owner = None
