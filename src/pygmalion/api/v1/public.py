"""公开 v1 传输适配；设备动作交由执行服务。"""

import asyncio
import json
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Header,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import Response as RawResponse

from ...schemas.canvas import (
    CanvasDocument,
    EditorDefaults,
    FitRequest,
    SvgImportRequest,
    Vector,
)
from ...schemas.public import (
    Backup,
    CalibrationPatch,
    CalibrationSettings,
    Capabilities,
    Collection,
    Command,
    ConfigResource,
    ConnectionPatch,
    ConnectionSettings,
    CreateJob,
    DeviceRequest,
    DocumentSummary,
    EditorPatch,
    ErrorResponse,
    Event,
    FirmwareChanges,
    FirmwarePreview,
    FitResult,
    Fonts,
    Health,
    ImportResult,
    Job,
    MachineSnapshot,
    Operation,
    Plan,
    QueueSnapshot,
    SerialPort,
    ServiceInfo,
    Session,
    SoftwarePatch,
    SoftwareSettings,
    Status,
    StoredDocument,
    ValidationResult,
)
from ...servicer import configuration, documents, system, workbench
from ...servicer.public_errors import PublicError
from ..dependencies import get_context

ERRORS = {
    code: {"model": ErrorResponse} for code in (400, 404, 409, 412, 422, 428, 500, 503)
}
router = APIRouter(prefix="/api/v1", responses=ERRORS)
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


def service(request):
    return get_context(request).execution


@router.get("/health", response_model=Health)
def health():
    return Health()


@router.get("/capabilities", response_model=Capabilities)
def capabilities(request: Request):
    return Capabilities(
        allowed_job_modes=["simulate"]
        if service(request).dry_run
        else ["execute", "simulate"]
    )


@router.get("/service", response_model=ServiceInfo)
def info():
    return ServiceInfo(urls=system.network()["urls"])


@router.get("/fonts", response_model=Fonts)
def fonts():
    data = system.list_fonts()
    return {"default": data["default"], "fonts": data["fonts"]}


@router.post("/documents", response_model=StoredDocument, status_code=201)
def create_document(data: CanvasDocument, response: Response, key: Key):
    result = documents.create(data, key)
    response.headers["ETag"] = f'"{result["revision"]}"'
    return result


@router.get("/documents", response_model=Collection[DocumentSummary])
def list_documents(limit: int = Query(default=100, ge=1, le=200)):
    return {"data": documents.list_documents(limit), "next_cursor": None}


@router.get("/documents/{identifier}", response_model=StoredDocument)
def get_document(identifier: str, response: Response):
    result = documents.get(identifier)
    response.headers["ETag"] = f'"{result["revision"]}"'
    return result


@router.put("/documents/{identifier}", response_model=StoredDocument)
def update_document(
    identifier: str,
    data: CanvasDocument,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):
    result = documents.update(identifier, data, if_match)
    response.headers["ETag"] = f'"{result["revision"]}"'
    return result


@router.post("/documents/validate", response_model=ValidationResult)
def validate(data: CanvasDocument):
    return ValidationResult()


@router.post("/documents/fit-table", response_model=FitResult)
def fit(data: FitRequest):
    result = workbench.fit_document_table(data)
    return {"element": result["table"], "diagnostics": result["diagnostics"]}


@router.post("/imports/svg", response_model=ImportResult)
def import_svg(data: SvgImportRequest):
    result = workbench.import_vector(data)
    return {"element": Vector(id=uuid.uuid4().hex, **result)}


@router.post("/plans", response_model=Plan, status_code=201)
def plan(request: Request, data: CanvasDocument):
    return service(request).prepare(data)


@router.get("/plans/{identifier}", response_model=Plan)
def get_plan(request: Request, identifier: str):
    return service(request).plan(identifier)["plan"]


@router.get(
    "/plans/{identifier}/preview",
    response_class=RawResponse,
    responses={200: {"content": {"image/svg+xml": {"schema": {"type": "string"}}}}},
)
def preview(request: Request, identifier: str):
    return RawResponse(
        service(request).plan(identifier)["svg"], media_type="image/svg+xml"
    )


@router.get("/queue", response_model=QueueSnapshot)
def queue_state(request: Request):
    return service(request).queue_snapshot()


@router.post("/jobs", response_model=Job, status_code=202)
def submit(request: Request, data: CreateJob, key: Key):
    return service(request).submit(data, key)


@router.get("/jobs/{identifier}", response_model=Job)
def job(request: Request, identifier: int):
    return service(request).job(identifier)


@router.get("/jobs", response_model=Collection[Job])
def jobs(
    request: Request,
    before: int | None = Query(default=None, ge=1),
    status: Status | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    data, cursor = service(request).list_jobs(before, status, limit)
    return {"data": data, "next_cursor": cursor}


@router.post("/jobs/{identifier}/cancel", response_model=Job)
def cancel(request: Request, identifier: int):
    return service(request).cancel(identifier)


@router.get("/machine", response_model=MachineSnapshot)
def machine(request: Request):
    return service(request).machine_snapshot()


@router.get("/serial-ports", response_model=Collection[SerialPort])
def ports(request: Request):
    return {"data": service(request).maintenance.ports()}


@router.post("/serial-probes", response_model=Operation, status_code=202)
def probe(request: Request, data: DeviceRequest, key: Key):
    return service(request).enqueue_operation("probe", data.model_dump(), key)


@router.post("/machine/refresh", response_model=Operation, status_code=202)
def refresh(request: Request, data: DeviceRequest, key: Key):
    return service(request).enqueue_operation("refresh", data.model_dump(), key)


@router.get("/operations/{identifier}", response_model=Operation)
def operation(request: Request, identifier: str):
    return service(request).operation(identifier)


@router.post("/machine/control-sessions", response_model=Session, status_code=201)
def acquire(request: Request, key: Key):
    return service(request).acquire(key)


@router.post("/machine/control-sessions/{identifier}/renew", response_model=Session)
def renew(request: Request, identifier: str):
    return service(request).renew(identifier)


@router.delete("/machine/control-sessions/{identifier}", response_model=Session)
def release(request: Request, identifier: str):
    return service(request).release(identifier)


@router.post("/machine/commands", response_model=Operation, status_code=202)
def command(request: Request, data: Command, key: Key):
    return service(request).enqueue_operation("command", data.model_dump(), key)


@router.post("/machine/emergency-stop", response_model=Operation, status_code=202)
def emergency(request: Request):
    return service(request).emergency()


@router.post("/machine/backups", response_model=Operation, status_code=202)
def backup(request: Request, data: DeviceRequest, key: Key):
    return service(request).enqueue_operation("backup", data.model_dump(), key)


@router.get("/machine/backups", response_model=Collection[Backup])
def backups(request: Request):
    return {"data": service(request).maintenance.backups()}


@router.get(
    "/machine/backups/{identifier}/download",
    response_class=RawResponse,
    responses={200: {"content": {"text/plain": {"schema": {"type": "string"}}}}},
)
def download(request: Request, identifier: str):
    try:
        data = service(request).maintenance.download(identifier)
    except (FileNotFoundError, ValueError) as exc:
        raise PublicError(404, "backup_not_found", "备份不存在") from exc
    return RawResponse(
        data,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{identifier}.txt"'},
    )


@router.post(
    "/machine/settings/previews", response_model=FirmwarePreview, status_code=201
)
def firmware(request: Request, data: FirmwareChanges):
    return service(request).firmware_preview(data)


@router.post(
    "/machine/settings/previews/{identifier}/apply",
    response_model=Operation,
    status_code=202,
)
def apply(request: Request, identifier: str, data: DeviceRequest, key: Key):
    return service(request).enqueue_operation(
        "firmware", {**data.model_dump(), "preview_id": identifier}, key
    )


def configuration_routes(path, kind, model, patch_model):
    def read(response: Response):
        result = configuration.read(kind)
        response.headers["ETag"] = result["etag"]
        return result

    def update(
        request: Request,
        response: Response,
        data,
        if_match: Annotated[str | None, Header()] = None,
    ):
        result = service(request).patch_config(kind, data, if_match)
        response.headers["ETag"] = result["etag"]
        return result

    update.__annotations__["data"] = patch_model
    router.add_api_route(
        path,
        read,
        methods=["GET"],
        response_model=ConfigResource[model],
        name=f"get_{kind}",
    )
    router.add_api_route(
        path,
        update,
        methods=["PATCH"],
        response_model=ConfigResource[model],
        name=f"patch_{kind}",
    )


for path, kind, model, patch_model in (
    ("/settings/software", "software", SoftwareSettings, SoftwarePatch),
    ("/settings/editor", "editor", EditorDefaults, EditorPatch),
    ("/settings/calibration", "calibration", CalibrationSettings, CalibrationPatch),
    ("/machine/connection", "connection", ConnectionSettings, ConnectionPatch),
):
    configuration_routes(path, kind, model, patch_model)


@router.websocket("/events")
async def events(socket: WebSocket):
    await socket.accept()
    runtime = get_context(socket).execution
    previous = {}
    try:
        while True:
            values = [
                ("machine.updated", runtime.machine_snapshot().model_dump(mode="json"))
            ]
            rows, _ = runtime.list_jobs(limit=50)
            values.extend(("job.updated", item) for item in rows)
            values.extend(
                ("operation.updated", item) for item in runtime.recent_operations()
            )
            for kind, data in values:
                key = (kind, str(data.get("id", "machine")))
                encoded = json.dumps(data, sort_keys=True)
                if previous.get(key) != encoded:
                    await socket.send_json(
                        Event.model_validate_json(
                            json.dumps({"type": kind, "data": data})
                        ).model_dump(mode="json")
                    )
                    previous[key] = encoded
            # 接收仅用于感知断线，不将任何客户端消息解释为控制命令。
            try:
                await asyncio.wait_for(socket.receive_text(), timeout=0.2)
            except TimeoutError:
                pass
    except (WebSocketDisconnect, RuntimeError):
        return
