"""真实 MCP JSON-RPC 握手、工具调用与共享数据库集成。"""

import pytest
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


def call(client, tool_name, **arguments):
    return rpc(client, "tools/call", {"name": tool_name, "arguments": arguments})


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
    assert "queue_job" not in tools
    assert tools["import_svg"]["annotations"]["readOnlyHint"]
    assert tools["import_svg"]["inputSchema"]["required"] == ["source"]
    assert (
        tools["import_svg"]["inputSchema"]["properties"]["source"]["maxLength"]
        == 1000000
    )
    assert tools["get_document"]["annotations"]["readOnlyHint"]
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


def test_mcp_preview_cannot_submit_but_can_query_tasks(client):
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
    denied = call(
        client,
        "queue_job",
        plan_id=plan["id"],
        mode="execute",
        idempotency_key="forbidden",
    )
    assert denied["isError"]
    assert client.get("/api/v1/jobs").json()["data"] == []
    job = client.post(
        "/api/v1/jobs",
        json={"plan_id": plan["id"], "mode": "simulate"},
        headers={"Idempotency-Key": "ui-simulate"},
    ).json()
    assert "queued_total" in result(call(client, "get_queue"))
    assert wait(client, f"/api/v1/jobs/{job['id']}")["status"] == "succeeded"
    assert result(call(client, "get_job", job_id=job["id"]))["status"] == "succeeded"


@pytest.mark.parametrize(
    "source,mode,width,height",
    [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="300mm" height="120mm" viewBox="0 0 300 120"><rect width="300" height="120" fill="none" stroke="black"/></svg>',
            "outline",
            300,
            120,
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="20mm" viewBox="0 0 40 20"><path d="M0 0H40V20H0Z M10 5H30V15H10Z" fill="black" fill-rule="evenodd"/></svg>',
            "solid",
            40,
            20,
        ),
    ],
    ids=["outline-original-size", "solid-evenodd"],
)
def test_mcp_import_svg_save_and_preview_existing_document(
    client, source, mode, width, height
):
    original = CanvasDocument(
        name="现有文档",
        elements=[TextBox(id="t", text="甲乙")],
        pen_anchor={"x_mm": 23.5, "y_mm": 29.5},
    ).model_dump()
    created = result(
        call(client, "create_document", document=original, idempotency_key="svg-target")
    )
    imported = result(call(client, "import_svg", source=source, name="智能体导入"))
    element = imported["element"]
    assert element["type"] == "vector" and element["name"] == "智能体导入"
    assert element["width_mm"] == pytest.approx(width)
    assert element["height_mm"] == pytest.approx(height)
    assert element["draw_mode"] == mode
    if mode == "solid":
        assert element["fill_rules"] == ["evenodd"]
    # 转换阶段没有修改目标文档，也没有创建任务。
    assert result(call(client, "get_document", document_id=created["id"])) == created
    assert client.get("/api/v1/jobs").json()["data"] == []
    http = client.post(
        "/api/v1/imports/svg", json={"source": source, "name": "智能体导入"}
    )
    assert http.status_code == 200
    assert {k: v for k, v in http.json()["element"].items() if k != "id"} == {
        k: v for k, v in element.items() if k != "id"
    }
    element.update(
        x_mm=-40, y_mm=100, width_mm=40, height_mm=16 if mode == "outline" else 20
    )
    document = {**original, "elements": [*original["elements"], element]}
    saved = result(
        call(
            client,
            "save_document",
            document_id=created["id"],
            revision=1,
            document=document,
        )
    )
    assert saved["revision"] == 2
    assert (
        client.get(f"/api/v1/documents/{created['id']}").json()["document"] == document
    )
    plan = result(
        call(client, "prepare_document", document_id=created["id"], revision=2)
    )
    assert plan["status"] == "ready" and plan["strokes"] > 1
    assert "<svg" in result(call(client, "get_plan_preview", plan_id=plan["id"]))["svg"]


@pytest.mark.parametrize(
    "source",
    [
        "<svg>",
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        '<!DOCTYPE svg [<!ENTITY x "abc">]><svg/>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/a.png"/></svg>',
        "x" * 1000001,
    ],
    ids=["malformed", "script", "dtd", "bitmap", "oversized"],
)
def test_mcp_import_svg_rejects_unsupported_or_oversized_sources(client, source):
    error = call(client, "import_svg", source=source)
    assert error["isError"]
    assert error["content"][0]["type"] == "text"
    assert result(call(client, "list_documents"))["data"] == []
    assert client.get("/api/v1/jobs").json()["data"] == []
