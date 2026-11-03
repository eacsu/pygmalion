"""速度边界由公开模型统一约束读取、保存和拒绝行为。"""

import pytest

from pygmalion import config


@pytest.mark.parametrize(
    "key,value",
    [
        ("feed_rate", 12000),
        ("jog_speed", 12000),
        ("z_speed", 8000),
        ("feed_rate", 50000),
    ],
)
def test_speed_settings_have_no_artificial_upper_limit(client, key, value):
    current = client.get("/api/v1/settings/software").json()
    assert next(f for f in current["fields"] if f["key"] == key)["max"] is None
    response = client.patch(
        "/api/v1/settings/software",
        json={key: value},
        headers={"If-Match": current["etag"]},
    )
    assert response.status_code == 200
    assert response.json()["values"][key] == value
    assert config.CONFIG["machine"][key] == value
    response = client.patch(
        "/api/v1/settings/software",
        json={key: -1},
        headers={"If-Match": response.json()["etag"]},
    )
    assert response.status_code == 422
    assert config.CONFIG["machine"][key] == value
