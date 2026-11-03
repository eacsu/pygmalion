import pytest

from pygmalion.machine.timing import estimate_seconds

MACHINE = {"feed_rate": 600, "jog_speed": 1200, "z_speed": 120, "z_on": 2}


def test_estimate_includes_rapid_feed_pen_lifts_dwell_and_return():
    program = [
        "; comment",
        "G21",
        "G90",
        "G0 Z0",
        "G0 X30 Y40",
        "G1 Z2 F120",
        "G1 X60 Y80 F600",
        "G0 Z0",
        "G4 P0.5",
        "G0 X0 Y0",
        "M2",
    ]
    assert estimate_seconds(program, MACHINE) == pytest.approx(16)


def test_estimate_uses_actual_start_and_handles_unknown_program():
    assert estimate_seconds(["G0 X30 Y40"], MACHINE, (30, 40)) == 0
    assert estimate_seconds(["G0 X30 Y40"], MACHINE) == 2.5
    assert estimate_seconds(["G20", "G1 X1"], MACHINE) is None
    assert estimate_seconds([], MACHINE) is None


def test_plan_and_job_publish_frozen_estimate(client):
    from pygmalion.schemas.canvas import CanvasDocument, Vector

    doc = CanvasDocument(elements=[Vector(id="v", paths=["M0 0 L1 1"])])
    plan = client.post("/api/v1/plans", json=doc.model_dump()).json()
    assert plan["estimated_duration_seconds"] > 0
    settings = client.get("/api/v1/settings/software").json()
    updated = client.patch(
        "/api/v1/settings/software",
        json={"feed_rate": settings["values"]["feed_rate"] * 2},
        headers={"If-Match": settings["etag"]},
    )
    assert updated.status_code == 200
    job = client.post(
        "/api/v1/jobs",
        json={"plan_id": plan["id"], "mode": "simulate"},
        headers={"Idempotency-Key": "timed-job"},
    ).json()
    assert job["estimated_duration_seconds"] == plan["estimated_duration_seconds"]
    assert (
        client.get(f"/api/v1/jobs/{job['id']}").json()["estimated_duration_seconds"]
        == job["estimated_duration_seconds"]
    )
