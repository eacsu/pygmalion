"""MCP 传输适配：与网页复用同一实例的文档和任务服务。"""

import json
from functools import wraps
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from ..schemas.canvas import CanvasDocument, FitRequest, SvgImportRequest
from ..schemas.circuit import CircuitElement
from ..schemas.public import CircuitRender, CircuitSymbols, ImportResult
from ..servicer import circuits, documents, workbench
from ..servicer.errors import ServiceError
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
    except ServiceError as exc:
        raise ToolError(f"{exc.kind}: {exc}") from exc


def create_mcp(application):
    server = FastMCP(
        "Pygmalion",
        instructions=(
            "操作此实例数据库中的书写文档。先 list_documents / get_document，"
            "保留现有元素 ID、未修改内容和笔头定位，所有排版坐标与尺寸使用毫米。"
            "save_document 必须传读取到的 revision；document_changed 时重新读取并合并，"
            "不得用新版本号强行覆盖他人内容。保存后网页会自动同步。"
            "导入 SVG 文件时，将文件内容传给 import_svg，调整返回 element 的毫米位置与尺寸，"
            "追加到文档 elements，再用 save_document 保存；导入本身不改文档、不移动机器。"
            "电路使用文档 v3 的 circuit 元素，先 list_circuit_symbols 查看元件和引脚，"
            "新增电路先调用 layout_circuit 自动整理，保存返回的 element；通过 render_circuit 校核结构与预览；保留照片中不确定项为 uncertainties，不猜测连接。"
            "prepare_document 生成冻结方案和预览，不移动机器。"
            "智能体仅可编辑和预览，不得提交书写任务、调用设备运动接口或启动实体机器。"
            "实际书写由用户在网页中操作；允许查询状态和请求停止。"
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
    def list_documents(
        limit: Annotated[int, Field(ge=1, le=200)] = 100,
    ) -> dict[str, Any]:
        """列出实例内最近更新的共享文档摘要，包含文档 ID 和版本。"""
        return {"data": documents.list_documents(limit)}

    @server.tool(annotations=read)
    @in_worker
    def get_document(document_id: str) -> dict[str, Any]:
        """读取完整文档、当前 revision；编辑前必须先读取。"""
        return checked(documents.get, document_id)

    @server.tool(annotations=write)
    @in_worker
    def create_document(
        document: CanvasDocument, idempotency_key: Key
    ) -> dict[str, Any]:
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
    def import_svg(
        source: Annotated[str, Field(max_length=1000000)],
        name: Annotated[str, Field(max_length=120)] = "矢量图",
    ) -> ImportResult:
        """解析 SVG 源码并返回标准矢量 element；调整位置后加入文档，再 save_document。

        支持路径、几何图形、分组变换、轮廓和填充；保留原始毫米尺寸。
        本地文件由调用者读取后传入 source，不接收服务端文件路径或 URL。
        """
        element = checked(
            workbench.import_vector, SvgImportRequest(source=source, name=name)
        )
        return ImportResult(element=element)

    @server.tool(annotations=read)
    @in_worker
    def list_circuit_symbols() -> CircuitSymbols:
        """返回电路图支持的元件类型、引脚名称、默认长度和符号标准。"""
        return CircuitSymbols.model_validate(checked(circuits.symbols))

    @server.tool(annotations=read)
    @in_worker
    def layout_circuit(element: CircuitElement) -> CircuitRender:
        """自动整理元件间距、正交连线与标注并适配元素尺寸；返回建议，不保存、不移动设备。生成电路优先调用本工具，再保存返回的 element。"""
        return CircuitRender.model_validate(checked(circuits.layout, element))

    @server.tool(annotations=read)
    @in_worker
    def render_circuit(element: CircuitElement) -> CircuitRender:
        """校核并渲染结构化电路，返回 SVG、元件/引脚几何和诊断；不保存或启动书写。"""
        return CircuitRender.model_validate(checked(circuits.render, element))

    @server.tool(annotations=read)
    @in_worker
    def fit_table(
        document_id: str, revision: Revision, element_id: str
    ) -> dict[str, Any]:
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
    def cancel_job(job_id: int) -> dict[str, Any]:
        """取消等待任务或停止运行任务；运行任务仍需等待设备收尾。"""
        return checked(execution().cancel, job_id).model_dump(mode="json")

    return server
