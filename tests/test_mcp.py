"""真实 MCP JSON-RPC 握手、工具调用与共享数据库集成。"""

import json

from mcp.types import LATEST_PROTOCOL_VERSION

from pygmalion.schemas.canvas import CanvasDocument, TextBox
from tests.test_public_api import wait

HEADERS = {"Accept": "application/json, text/event-stream"}


def rpc(client, method, params=None):
    response = client.post(
        "/mcp/",
        headers=HEADERS,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def call(client, name, **arguments):
    return rpc(client, "tools/call", {"name": name, "arguments": arguments})


def result(value):
    assert not value.get("isError"), value
    return value["structuredContent"]


def test_mcp_handshake_catalog_and_stateless_connections(client):
    info = rpc(
        client,
        "initialize",
        {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "Codex integration test", "version": "1"},
        },
    )
    assert info["serverInfo"]["name"] == "Pygmalion"
    assert "save_document" in info["instructions"]
    tools = {t["name"]: t for t in rpc(client, "tools/list")["tools"]}
    assert len(tools) == 11
    assert tools["get_document"]["annotations"]["readOnlyHint"]
    assert tools["queue_job"]["annotations"]["openWorldHint"]
    assert set(tools["queue_job"]["inputSchema"]["required"]) == {
        "plan_id",
        "mode",
        "idempotency_key",
    }
    assert client.get("/api/v1/health").status_code == 200


def test_mcp_layout_edits_share_database_and_reject_stale_overwrites(client):
    document = CanvasDocument(
        name="智能体排版", elements=[TextBox(id="title", text="甲")]
    ).model_dump()
    created = result(
        call(client, "create_document", document=document, idempotency_key="mcp-doc")
    )
    identifier = created["id"]
    loaded = result(call(client, "get_document", document_id=identifier))
    assert loaded == client.get(f"/api/v1/documents/{identifier}").json()
    document["elements"][0]["x_mm"] = -35
    document["elements"][0]["font_size_mm"] = 12
    saved = result(
        call(
            client,
            "save_document",
            document_id=identifier,
            revision=1,
            document=document,
        )
    )
    assert saved["revision"] == 2
    assert client.get(f"/api/v1/documents/{identifier}").json()["document"] == document
    conflict = call(
        client,
        "save_document",
        document_id=identifier,
        revision=1,
        document={**document, "name": "旧智能体"},
    )
    assert conflict["isError"]
    assert "document_changed" in conflict["content"][0]["text"]
    invalid = {**document, "elements": [{**document["elements"][0], "width_mm": -1}]}
    assert call(
        client, "save_document", document_id=identifier, revision=2, document=invalid
    )["isError"]
    assert result(call(client, "get_document", document_id=identifier))["revision"] == 2
    assert result(call(client, "list_documents"))["data"][0]["id"] == identifier
    assert call(client, "get_document", document_id="missing")["isError"]


def test_mcp_preview_and_idempotent_simulated_queue(client):
    document = CanvasDocument(elements=[TextBox(id="t", text="甲乙")]).model_dump()
    created = result(
        call(
            client, "create_document", document=document, idempotency_key="preview-doc"
        )
    )
    assert call(client, "prepare_document", document_id=created["id"], revision=2)[
        "isError"
    ]
    plan = result(
        call(client, "prepare_document", document_id=created["id"], revision=1)
    )
    assert plan["status"] == "ready"
    svg = result(call(client, "get_plan_preview", plan_id=plan["id"]))["svg"]
    assert svg == client.get(plan["preview_url"]).text
    assert "<svg" in svg
    arguments = {
        "plan_id": plan["id"],
        "mode": "simulate",
        "idempotency_key": "mcp-job",
    }
    job = result(call(client, "queue_job", **arguments))
    assert result(call(client, "queue_job", **arguments))["id"] == job["id"]
    queue = result(call(client, "get_queue"))
    assert "running" in queue and "queued_total" in queue
    assert wait(client, f"/api/v1/jobs/{job['id']}")["status"] == "succeeded"
    assert result(call(client, "get_job", job_id=job["id"]))["status"] == "succeeded"
    # 没有隐式实机模式；演练实例拒绝请求真实书写。
    error = call(
        client,
        "queue_job",
        plan_id=plan["id"],
        mode="execute",
        idempotency_key="mcp-real",
    )
    assert error["isError"]
    assert "execution_disabled" in json.dumps(error, ensure_ascii=False)
