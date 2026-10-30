"""速度边界由公开模型统一约束读取、保存和拒绝行为。"""

import pytest

from pygmalion import config


@pytest.mark.parametrize(
    "key,limit", [("feed_rate", 8000), ("jog_speed", 8000), ("z_speed", 10000)]
)
def test_increased_speed_limit_is_advertised_saved_and_enforced(client, key, limit):
    current = client.get("/api/v1/settings/software").json()
    assert next(f for f in current["fields"] if f["key"] == key)["max"] == limit
    response = client.patch(
        "/api/v1/settings/software",
        json={key: limit},
        headers={"If-Match": current["etag"]},
    )
    assert response.status_code == 200
    assert response.json()["values"][key] == limit
    assert config.CONFIG["machine"][key] == limit
    response = client.patch(
        "/api/v1/settings/software",
        json={key: limit + 100},
        headers={"If-Match": response.json()["etag"]},
    )
    assert response.status_code == 422
    assert config.CONFIG["machine"][key] == limit
