"""FastAPI 托管 API 和 React 构建产物。"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..schemas.public import ErrorResponse, Event, Problem
from ..servicer.context import ServiceContext
from ..servicer.errors import ServiceError
from ..servicer.public_errors import PublicError
from .v1.public import router

logger = logging.getLogger(__name__)
WEB_DIST_DIR = Path(__file__).resolve().parents[2] / "web" / "dist"


def create_app(
    dist_dir: Path = WEB_DIST_DIR,
    dry_run: bool | None = None,
    *,
    serve_frontend: bool | None = None,
) -> FastAPI:
    if serve_frontend is None:
        serve_frontend = os.getenv("PYGMALION_API_ONLY", "0") != "1"

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if serve_frontend and not (dist_dir / "index.html").is_file():
            raise RuntimeError("前端构建不存在，请先在 src/web 执行 pnpm run build")
        context = ServiceContext(
            dry_run=dry_run
            if dry_run is not None
            else os.getenv("PYGMALION_DRY_RUN", "0") == "1"
        )
        application.state.services = context
        try:
            context.start()
            logger.info("书写工作区启动，任务演练=%s", context.execution.dry_run)
            yield
        finally:
            context.stop()

    application = FastAPI(title="Pygmalion · 写字机控制台", lifespan=lifespan)
    application.include_router(router)

    @application.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = "req_" + uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    def error_response(request, status, problem):
        identifier = getattr(request.state, "request_id", "req_" + uuid.uuid4().hex)
        return JSONResponse(
            ErrorResponse(error=problem, request_id=identifier).model_dump(mode="json"),
            status_code=status,
            headers={"X-Request-ID": identifier},
        )

    @application.exception_handler(PublicError)
    async def public_error(request, exc):
        return error_response(request, exc.status, exc.problem)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        invalid_json = any(item["type"] == "json_invalid" for item in exc.errors())
        details = {
            "violations": [
                {
                    "path": list(item["loc"]),
                    "message": item["msg"],
                    "type": item["type"],
                }
                for item in exc.errors()
            ]
        }
        return error_response(
            request,
            400 if invalid_json else 422,
            Problem(
                code="invalid_json" if invalid_json else "validation_error",
                message="请求字段不正确",
                details=details,
            ),
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return error_response(
            request,
            exc.status_code,
            Problem(
                code="not_found" if exc.status_code == 404 else "http_error",
                message=str(exc.detail),
            ),
        )

    @application.exception_handler(ServiceError)
    async def service_error(request, exc):
        return error_response(
            request,
            422,
            Problem(code=exc.kind, message=exc.payload.get("error", "操作失败")),
        )

    @application.exception_handler(Exception)
    async def unexpected(request, exc):
        logger.exception("请求处理失败", exc_info=exc)
        return error_response(
            request,
            500,
            Problem(
                code="internal_error",
                message="服务内部错误",
                retry_advice="query_status",
            ),
        )

    @application.api_route(
        "/api",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    @application.api_route(
        "/api/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    def api_not_found(path: str = ""):
        raise HTTPException(status_code=404, detail=f"API route not found: /api/{path}")

    if serve_frontend:
        application.frontend(
            "/", directory=dist_dir, fallback="index.html", check_dir=False
        )
    original_openapi = application.openapi

    def openapi():
        schema = original_openapi()
        event = Event.model_json_schema(ref_template="#/components/schemas/{model}")
        schema["components"]["schemas"].update(event.pop("$defs", {}))
        schema["components"]["schemas"]["Event"] = event
        schema["x-websocket"] = {
            "/api/v1/events": {
                "message_schema": {"$ref": "#/components/schemas/Event"},
                "control": False,
                "recovery": "query HTTP snapshots; never replay commands",
            }
        }
        return schema

    application.openapi = openapi
    return application


app = create_app()
