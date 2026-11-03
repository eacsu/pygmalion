"""MCP 传输适配：与网页复用同一实例的文档和任务服务。"""

import json
from functools import wraps
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from ..schemas.canvas import CanvasDocument, FitRequest
from ..schemas.public import CreateJob
from ..servicer import documents, workbench
from ..servicer.public_errors import PublicError

Revision = Annotated[int, Field(ge=1)]
Key = Annotated[str, Field(min_length=1, max_length=200)]


def in_worker(function):
    """字库排版与串口确认不阻塞同一实例的网页和状态查询。"""

    @wraps(function)
    async def wrapped(*args, **kwargs):
        return await run_in_threadpool(function, *args, **kwargs)

    return wrapped


def checked(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except PublicError as exc:
        raise ToolError(
            json.dumps(exc.problem.model_dump(mode="json"), ensure_ascii=False)
        ) from exc


def create_mcp(application):
    server = FastMCP(
        "Pygmalion",
        instructions=(
            "操作此实例数据库中的书写文档。先 list_documents / get_document，"
            "保留现有元素 ID、未修改内容和笔头定位，所有排版坐标与尺寸使用毫米。"
            "save_document 必须传读取到的 revision；document_changed 时重新读取并合并，"
            "不得用新版本号强行覆盖他人内容。保存后网页会自动同步。"
            "prepare_document 生成冻结方案和预览，不移动机器。"
            "只有用户明确要求书写时才 queue_job；execute 会操作实体机器，"
            "simulate 为演练。重试提交必须复用原 idempotency_key、plan_id 和 mode。"
        ),
        host="0.0.0.0",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )
    read = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    write = ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, openWorldHint=False
    )

    def execution():
        return application.state.services.execution

    def document_at(identifier, revision):
        value = checked(documents.get, identifier)
        if value["revision"] != revision:
            raise ToolError("document_changed: 文档版本已改变，请重新读取并合并修改")
        return CanvasDocument.model_validate(value["document"])

    @server.tool(annotations=read)
    @in_worker
    def list_documents(limit: Annotated[int, Field(ge=1, le=200)] = 100) -> dict[str, Any]:
        """列出实例内最近更新的共享文档摘要，包含文档 ID 和版本。"""
        return {"data": documents.list_documents(limit)}

    @server.tool(annotations=read)
    @in_worker
    def get_document(document_id: str) -> dict[str, Any]:
        """读取完整文档、当前 revision；编辑前必须先读取。"""
        return checked(documents.get, document_id)

    @server.tool(annotations=write)
    @in_worker
    def create_document(document: CanvasDocument, idempotency_key: Key) -> dict[str, Any]:
        """创建独立的共享文档；重试同一次创建须复用去重键。"""
        return documents.create(document, idempotency_key)

    @server.tool(annotations=write)
    @in_worker
    def save_document(
        document_id: str, revision: Revision, document: CanvasDocument
    ) -> dict[str, Any]:
        """按所读版本保存完整文档排版；冲突不会覆盖服务端内容。"""
        return checked(documents.update, document_id, document, f'"{revision}"')

    @server.tool(annotations=read)
    @in_worker
    def fit_table(document_id: str, revision: Revision, element_id: str) -> dict[str, Any]:
        """计算表格自适应建议，不保存；检查返回元素后再 save_document。"""
        document = document_at(document_id, revision)
        return workbench.fit_document_table(
            FitRequest(document=document, element_id=element_id)
        )

    @server.tool(annotations=write)
    @in_worker
    def prepare_document(document_id: str, revision: Revision) -> dict[str, Any]:
        """准备指定文档版本的冻结方案、预计用时及校核结果，不移动机器。"""
        document = document_at(document_id, revision)
        return checked(execution().prepare, document).model_dump(mode="json")

    @server.tool(annotations=read)
    @in_worker
    def get_plan_preview(plan_id: str) -> dict[str, Any]:
        """读取冻结方案的 SVG 笔迹预览；与后续提交的轨迹一致。"""
        value = checked(execution().plan, plan_id)
        return {"plan_id": plan_id, "svg": value["svg"]}

    @server.tool(annotations=read)
    @in_worker
    def get_queue() -> dict[str, Any]:
        """读取实例的运行任务、等待任务和等待总数。"""
        return execution().queue_snapshot()

    @server.tool(annotations=read)
    @in_worker
    def get_job(job_id: int) -> dict[str, Any]:
        """按 ID 查询任务状态、进度及结果，不重新提交任务。"""
        return checked(execution().job, job_id).model_dump(mode="json")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
    @in_worker
    def queue_job(
        plan_id: str,
        mode: Literal["simulate", "execute"],
        idempotency_key: Key,
    ) -> dict[str, Any]:
        """用户要求书写后提交方案；execute 操作实体机器，simulate 仅演练。"""
        return checked(
            execution().submit,
            CreateJob(plan_id=plan_id, mode=mode),
            idempotency_key,
        ).model_dump(mode="json")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
    @in_worker
    def cancel_job(job_id: int) -> dict[str, Any]:
        """取消等待任务或停止运行任务；运行任务仍需等待设备收尾。"""
        return checked(execution().cancel, job_id).model_dump(mode="json")

    return server
