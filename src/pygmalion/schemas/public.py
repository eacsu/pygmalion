"""公开 v1 契约；不依赖传输、设备或存储实现。"""

from typing import Annotated, Generic, Literal, TypeVar

from pydantic import Field, JsonValue, RootModel, model_validator

from .canvas import CanvasDocument, EditorDefaults, Model, Table, Vector

Status = Literal[
    "queued", "running", "cancelling", "succeeded", "cancelled", "failed", "interrupted"
]
Mode = Literal["execute", "simulate"]


class Problem(Model):
    code: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)
    retry_advice: Literal["never", "wait", "query_status", "reprepare", "refresh"] = (
        "never"
    )


class ErrorResponse(Model):
    error: Problem
    request_id: str


T = TypeVar("T")


class Collection(Model, Generic[T]):
    data: list[T]
    next_cursor: int | None = None


class Health(Model):
    status: Literal["ok"] = "ok"


class Capabilities(Model):
    document_versions: list[int] = Field(default_factory=lambda: [2])
    allowed_job_modes: list[Mode]
    max_active_jobs: int = 1
    max_elements: int = 100
    max_characters: int = 20000
    plan_expires: bool = False
    control_session_ttl_seconds: int = 30
    units: dict[str, str] = Field(
        default_factory=lambda: {"length": "mm", "speed": "mm/min"}
    )


class ServiceInfo(Model):
    version: str = "1"
    urls: list[str]


class Font(Model):
    id: str
    file: str
    label: str
    sublabel: str
    notes: str
    chars: int
    avg_points: float
    kind: str
    available: bool
    error: str


class Fonts(Model):
    default: str
    fonts: list[Font]


class Diagnostic(Model):
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    element_id: str | None = None
    row: int | None = None
    col: int | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ValidationResult(Model):
    valid: bool = True
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class FitResult(Model):
    element: Table
    diagnostics: list[Diagnostic]


class ImportResult(Model):
    element: Vector


class SoftwareSettings(Model):
    z_off: float = Field(
        default=0,
        ge=0.0,
        le=30.0,
        title="抬笔高度",
        description="笔离开纸面多高。太小会蹭纸、笔尖拖出毛边；太大浪费时间。只要不蹭纸，越小越好。",
        json_schema_extra={"unit": "mm", "step": 0.1},
    )
    z_on: float = Field(
        default=2,
        ge=0.0,
        le=30.0,
        title="落笔高度",
        description="落笔时 Z 走到多低。值越大压得越深。太浅写不上，太深戳纸、笔尖容易劈。建议从 2.0 开始，以「线条清晰且不戳穿纸」为准。",
        json_schema_extra={"unit": "mm", "step": 0.1},
    )
    table_segment_mm: float = Field(
        default=5,
        ge=0.5,
        le=20.0,
        title="表格框线分段长度",
        description="每段画完抬笔，从同一端点继续，保持实线。默认每段最多 5 mm；只作用于表格框线。",
        json_schema_extra={"unit": "mm", "step": 0.5},
    )
    stroke_delay: float = Field(
        default=0,
        ge=0.0,
        le=2.0,
        title="每笔停顿",
        description="每写完一笔停多久再写下一笔。笔画密的地方连续快速落笔，墨水来不及跟上会出现起笔断线。停一下让墨水润开。0 = 不停，速度最快。",
        json_schema_extra={"unit": "秒", "step": 0.05},
    )
    z_speed: float = Field(
        default=3000,
        ge=100.0,
        le=10000.0,
        title="抬落笔速度",
        description="Z 轴升降快慢。太快落笔冲击大、可能丢步；太慢每笔都拖时间。",
        json_schema_extra={"unit": "mm/min", "step": 100.0},
    )
    feed_rate: float = Field(
        default=3000,
        ge=100.0,
        le=8000.0,
        title="书写速度",
        description="落笔状态下画线的速度。实际速度受控制板 $110/$111 参数限制。写太快笔画会飘、转折处发虚。",
        json_schema_extra={"unit": "mm/min", "step": 100.0},
    )
    jog_speed: float = Field(
        default=3000,
        ge=100.0,
        le=8000.0,
        title="空走速度",
        description="抬笔状态下笔画之间移动的速度。不影响笔迹，只影响总耗时，可以设得比书写速度快。",
        json_schema_extra={"unit": "mm/min", "step": 100.0},
    )


class CalibrationSettings(Model):
    paper_preset: str = "A4"
    width_mm: float = Field(default=210, ge=20, le=1500)
    height_mm: float = Field(default=297, ge=20, le=1500)
    grid_width_mm: float = Field(default=190, ge=50, le=400)
    grid_height_mm: float = Field(default=280, ge=50, le=400)
    paper_offset_x_mm: float = Field(default=-20, ge=-100, le=400)
    paper_offset_y_mm: float = Field(default=-17, ge=-50, le=400)
    paper_min_x_mm: float = -100
    paper_min_y_mm: float = -50
    axes_swapped: bool = True
    invert_x: bool = True
    invert_y: bool = False
    offset_x: float = 0
    offset_y: float = 0
    fixed_grid_origin: bool = True
    origin_corner: Literal["左上", "右上", "左下", "右下"] = "左上"

    @model_validator(mode="after")
    def fits(self):
        if not (
            self.paper_min_x_mm <= self.paper_offset_x_mm
            and self.paper_min_y_mm <= self.paper_offset_y_mm
            and self.paper_offset_x_mm + self.width_mm <= self.grid_width_mm + 1e-6
            and self.paper_offset_y_mm + self.height_mm <= self.grid_height_mm + 1e-6
        ):
            raise ValueError("纸张必须落在写字盘范围内")
        return self


class ConnectionSettings(Model):
    port: str = Field(default="auto", min_length=1, max_length=300)
    baud: int = Field(default=115200, ge=1200, le=4000000)


class SettingField(Model):
    key: str
    label: str
    unit: str
    min: float
    max: float
    step: float
    help: str
    value: float


class PaperPreset(Model):
    id: str
    name: str
    group: str
    width_mm: float
    height_mm: float


class ConfigResource(Model, Generic[T]):
    values: T
    etag: str
    fields: list[SettingField] = Field(default_factory=list)
    paper_presets: list[PaperPreset] = Field(default_factory=list)


class SerialPort(Model):
    device: str
    description: str
    hwid: str | None = None
    vid: int | None = None
    pid: int | None = None
    reachable: bool | None = None
    grbl: bool | None = None
    firmware: str = ""
    error: str = ""


class MachineSnapshot(Model):
    port: str | None = None
    baud: int = 115200
    state: dict[str, str] = Field(default_factory=dict)
    firmware: list[str] = Field(default_factory=list)
    sampled_at: str | None = None
    stale: bool = True
    connected: bool = False


class Backup(Model):
    id: str
    created_at: str
    download_url: str


class DeviceResult(Model):
    kind: Literal[
        "refresh", "probe", "command", "backup", "firmware", "release", "emergency"
    ]
    machine: MachineSnapshot | None = None
    ports: list[SerialPort] = Field(default_factory=list)
    backup: Backup | None = None
    action: str | None = None
    applied: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)
    not_applied: list[str] = Field(default_factory=list)
    command_sent: bool | None = None
    stop_confirmed: bool | None = None


class Operation(Model):
    id: str
    kind: str
    status: Status
    created_at: str
    updated_at: str
    result: DeviceResult | None = None
    error: Problem | None = None


class Plan(Model):
    id: str
    status: Literal["ready", "blocked"]
    created_at: str
    expires_at: None = None
    document: CanvasDocument
    diagnostics: list[Diagnostic]
    preview_url: str
    context_hash: str
    software: SoftwareSettings
    fonts: list[str]
    strokes: int
    cells: int


class CreateJob(Model):
    plan_id: str
    mode: Mode


class Job(Model):
    id: int
    plan_id: str | None = None
    mode: Mode
    status: Status
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    sent: int = 0
    total: int = 0
    percent: float = 0
    title: str = ""
    message: str = ""
    error: Problem | None = None
    pen_position: list[float] | None = Field(default=None, min_length=2, max_length=2)


class Session(Model):
    id: str
    expires_at: str
    status: Literal["active", "closing", "expired", "released"] = "active"


class DeviceRequest(Model):
    session_id: str | None = None


class JogCommand(DeviceRequest):
    type: Literal["jog"]
    axis: Literal["x", "y"]
    distance_mm: float

    @model_validator(mode="after")
    def distance(self):
        if not 0.01 <= abs(self.distance_mm) <= 60:
            raise ValueError("单次点动应在 0.01–60 mm 内")
        return self


class SimpleCommand(DeviceRequest):
    type: Literal[
        "pen_up",
        "pen_down",
        "set_origin",
        "goto_origin",
        "recover",
        "disconnect",
        "cancel_pending",
    ]


Command = Annotated[JogCommand | SimpleCommand, Field(discriminator="type")]


class FirmwareChanges(Model):
    changes: dict[str, float] = Field(min_length=1)


class FirmwarePreview(Model):
    id: str
    changes: dict[str, float]
    commands: list[str]
    context_hash: str


class MachineEvent(Model):
    type: Literal["machine.updated"]
    data: MachineSnapshot


class JobEvent(Model):
    type: Literal["job.updated"]
    data: Job


class OperationEvent(Model):
    type: Literal["operation.updated"]
    data: Operation


class Event(
    RootModel[
        Annotated[MachineEvent | JobEvent | OperationEvent, Field(discriminator="type")]
    ]
):
    pass


# PATCH 保留字段约束，未提供的字段不会覆盖当前值。
def _patch_model(name, model):
    from copy import deepcopy

    from pydantic import create_model

    fields = {}
    for key, info in model.model_fields.items():
        field = deepcopy(info)
        field.default = None
        fields[key] = (info.annotation | None, field)
    return create_model(name, __base__=Model, **fields)


SoftwarePatch = _patch_model("SoftwarePatch", SoftwareSettings)
CalibrationPatch = _patch_model("CalibrationPatch", CalibrationSettings)
ConnectionPatch = _patch_model("ConnectionPatch", ConnectionSettings)
EditorPatch = _patch_model("EditorPatch", EditorDefaults)
