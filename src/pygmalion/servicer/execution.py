"""公开执行生命周期：持久任务、可追踪操作以及共同设备仲裁。"""

import copy
import json
import logging
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from .. import config
from ..execution import repository as store
from ..machine.controller import DeviceController
from ..machine.errors import ExecutionCancelled, ExecutionRejected
from ..machine.maintenance import Maintenance
from ..machine.timing import estimate_seconds
from ..plans.service import bind_anchor, context_hash, create_plan, fingerprint
from ..schemas.public import (
    DeviceResult,
    FirmwarePreview,
    Job,
    MachineSnapshot,
    Operation,
    Problem,
    Session,
)
from ..storage import RuntimeLock
from . import configuration
from .public_errors import PublicError

logger = logging.getLogger(__name__)
TERMINAL = set(store.TERMINAL)


def failure(code, message, advice="query_status"):
    return Problem(code=code, message=message, retry_advice=advice).model_dump(
        mode="json"
    )


class ExecutionService:
    def __init__(self, controller=None, *, dry_run=False):
        self.machine = controller or DeviceController()
        self.maintenance = Maintenance(self.machine)
        self.dry_run = dry_run
        self.halted = False
        self.lock = threading.RLock()
        self.runtime_lock = RuntimeLock()
        self.owner = None
        self.session = None
        self.session_token = None
        self.deadline = 0.0
        self.session_history = {}
        self.session_keys = {}
        self.pending = {}
        self.cancel_flags = {}
        self.snapshot = MachineSnapshot()
        self.snapshot_time = 0.0
        self.stopping = threading.Event()
        self.jobs = queue.Queue()
        self.pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="device-operation"
        )
        self.threads = []
        self.machine.busy = lambda: self.owner is not None and self.owner[0] == "job"

    def start(self):
        self.runtime_lock.acquire()
        store.initialize()
        self.stopping.clear()
        for target, name in (
            (self._job_worker, "execution-worker"),
            (self._monitor, "device-monitor"),
        ):
            worker = threading.Thread(target=target, name=name, daemon=True)
            worker.start()
            self.threads.append(worker)

    def stop(self):
        self.stopping.set()
        for flag in self.cancel_flags.values():
            flag.set()
        self.jobs.put(None)
        for thread in self.threads:
            thread.join(timeout=5)
        self.pool.shutdown(wait=True, cancel_futures=True)
        if self.session_token:
            self.machine.end_session(self.session_token)
        self.machine.stop()
        if not any(thread.is_alive() for thread in self.threads):
            self.runtime_lock.release()

    def _expire(self):
        if self.session and self.deadline <= time.monotonic():
            self._release_session("expired")

    def _release_session(self, status):
        if not self.session:
            return
        self.session.status = status
        self.session_history[self.session.id] = self.session.model_copy(deep=True)
        self._cancel_pending(self.session.id)
        if any(
            v["session"] == self.session.id and v["running"]
            for v in self.pending.values()
        ):
            self.session.status = "closing"
            return
        if self.session_token:
            self.machine.end_session(self.session_token)
        self.session = None
        self.session_token = None
        self.owner = None

    def _monitor(self):
        while not self.stopping.wait(0.2):
            if not self.lock.acquire(blocking=False):
                continue
            try:
                self._expire()
                if (
                    self.session
                    and not self.pending
                    and self.session.status == "active"
                ):
                    try:
                        state = self.machine.manual_status()
                        if state:
                            self._record_machine(
                                {
                                    "state": state,
                                    "port": config.CONFIG["machine"]["port"],
                                }
                            )
                    except Exception:
                        logger.exception("设备采样连接中断")
                        self.snapshot_time = 0
                        self.snapshot.connected = False
            finally:
                self.lock.release()

    def _record_machine(self, result):
        self.snapshot = MachineSnapshot(
            port=result.get("port", self.snapshot.port),
            baud=config.CONFIG["machine"]["baud"],
            state=result.get("state", self.snapshot.state),
            firmware=result.get("firmware", self.snapshot.firmware),
            sampled_at=store.now(),
            stale=False,
            connected=True,
        )
        self.snapshot_time = time.monotonic()
        return self.machine_snapshot()

    def machine_snapshot(self):
        result = self.snapshot.model_copy(deep=True)
        result.stale = time.monotonic() - self.snapshot_time > 2
        return result

    def queue_snapshot(self):
        return store.queue_snapshot()

    def list_jobs(self, before=None, status=None, limit=50):
        return store.list_jobs(before, status, limit)

    def recent_operations(self):
        return store.list_operations()

    def plan(self, identifier):
        data = store.get_plan(identifier)
        if data is None:
            raise PublicError(404, "plan_not_found", "方案不存在")
        return data

    def prepare(self, document):
        with self.lock:
            return create_plan(document)

    def job(self, identifier):
        row = store.get_resource("jobs", identifier)
        if not row:
            raise PublicError(404, "job_not_found", "任务不存在")
        return Job.model_validate_json(row["data"])

    def operation(self, identifier):
        row = store.get_resource("operations", identifier)
        if not row:
            raise PublicError(404, "operation_not_found", "操作不存在")
        return Operation.model_validate_json(row["data"])

    def _key(self, scope, key, payload):
        if not key or len(key) > 200:
            raise PublicError(
                422, "idempotency_key_required", "需要 1–200 字符的 Idempotency-Key"
            )
        value = fingerprint(payload)
        try:
            existing = store.find_key(scope, key, value)
        except store.Conflict as exc:
            raise PublicError(
                409, "idempotency_conflict", "该去重键已用于其他请求"
            ) from exc
        return existing, value

    def submit(self, request, key):
        with self.lock:
            payload = request.model_dump(mode="json")
            existing, digest = self._key("jobs", key, payload)
            if existing:
                return self.job(int(existing))
            self._expire()
            if self.owner and self.owner[0] != "job":
                raise PublicError(
                    409,
                    "machine_busy",
                    "设备由手动控制会话占用，请释放后提交",
                    advice="wait",
                )
            bundle = self.plan(request.plan_id)
            plan = bundle["plan"]
            if plan["status"] != "ready":
                raise PublicError(
                    409,
                    "plan_blocked",
                    "方案存在阻止执行的问题",
                    advice="reprepare",
                    details={"diagnostics": plan["diagnostics"]},
                )
            if request.mode == "execute" and self.halted:
                raise PublicError(409, "emergency_active", "急停后需显式恢复设备")
            if request.mode == "execute" and self.dry_run:
                raise PublicError(409, "execution_disabled", "服务只允许模拟书写")
            if plan["context_hash"] != context_hash():
                raise PublicError(
                    409,
                    "execution_context_changed",
                    "设备连接或定位校准已改变，请重新准备",
                    advice="reprepare",
                )
            snapshot = copy.deepcopy(bundle)
            position = None
            snapshot["position_pending"] = (
                request.mode == "execute" and self.owner is not None
            )
            if request.mode == "execute" and not snapshot["position_pending"]:
                try:
                    reference = self.machine.read_anchor_position()
                    snapshot["machine"].update(
                        port=reference["port"], execution_position=reference["position"]
                    )
                    if plan["document"].get("pen_anchor"):
                        position = reference["position"]
                        snapshot["program"] = bind_anchor(
                            snapshot["program"], position, snapshot["page"]
                        )
                        snapshot["machine"]["pen_anchor_position"] = position
                except ValueError as exc:
                    raise PublicError(
                        503, "position_unavailable", str(exc), advice="refresh"
                    ) from exc
            elif plan["document"].get("pen_anchor"):
                position = (0.0, 0.0)
            data = Job(
                id=0,
                plan_id=request.plan_id,
                mode=request.mode,
                status="queued",
                created_at=store.now(),
                title=plan["document"]["name"],
                total=sum(
                    bool(line.strip()) and not line.strip().startswith(";")
                    for line in snapshot["program"]
                ),
                estimated_duration_seconds=estimate_seconds(
                    snapshot["program"],
                    snapshot["machine"],
                    snapshot["machine"].get("execution_position", (0.0, 0.0)),
                ),
                pen_position=list(position) if position is not None else None,
            ).model_dump(mode="json")
            identifier, created = store.create_resource(
                "jobs", data, snapshot, key, digest
            )
            if created:
                if self.owner is None:
                    self.owner = ("job", int(identifier))
                self.cancel_flags[int(identifier)] = threading.Event()
                self.jobs.put(int(identifier))
            return self.job(int(identifier))

    def cancel(self, identifier):
        with self.lock:
            job = self.job(identifier)
            if job.status in ("cancelled", "cancelling"):
                return job
            if job.status in TERMINAL:
                raise PublicError(409, "job_terminal", "任务已经结束")
            self.cancel_flags.setdefault(identifier, threading.Event()).set()
            job.status = "cancelled" if job.status == "queued" else "cancelling"
            if job.status == "cancelled":
                job.finished_at = store.now()
            store.update_resource("jobs", job.model_dump(mode="json"))
            return job

    def _reserve_next(self):
        identifier = store.next_queued_job()
        self.owner = ("job", identifier) if identifier is not None else None

    def _job_worker(self):
        while True:
            identifier = self.jobs.get()
            if identifier is None:
                return
            with self.lock:
                job = self.job(identifier)
                if job.status == "cancelled":
                    if self.owner == ("job", identifier):
                        self._reserve_next()
                    self.cancel_flags.pop(identifier, None)
                    continue
                job.status = "running"
                job.started_at = store.now()
                store.update_resource("jobs", job.model_dump(mode="json"))
            flag = self.cancel_flags[identifier]
            row = store.get_resource("jobs", identifier)
            snapshot = json.loads(row["snapshot"])
            touched = False
            try:
                if snapshot["plan"]["context_hash"] != context_hash():
                    raise PublicError(
                        409,
                        "execution_context_changed",
                        "执行上下文已改变",
                        advice="reprepare",
                    )

                def progress(sent, total, *, job=job, flag=flag):
                    job.sent = sent
                    job.total = total
                    job.percent = round(sent / max(1, total) * 100, 1)
                    job.status = "cancelling" if flag.is_set() else "running"
                    store.update_resource("jobs", job.model_dump(mode="json"))

                if job.mode == "simulate":
                    for sent in range(0, job.total, max(1, job.total // 30)):
                        if flag.is_set():
                            break
                        progress(min(sent + 1, job.total), job.total)
                        time.sleep(0.005)
                    if not flag.is_set():
                        progress(job.total, job.total)
                else:
                    if self.halted:
                        raise PublicError(
                            409, "emergency_active", "急停后需显式恢复设备"
                        )
                    if snapshot.get("position_pending"):
                        try:
                            reference = self.machine.read_anchor_position()
                        except ValueError as exc:
                            raise PublicError(
                                503, "position_unavailable", str(exc), advice="refresh"
                            ) from exc
                        snapshot["machine"].update(
                            port=reference["port"],
                            execution_position=reference["position"],
                        )
                        if snapshot["plan"]["document"].get("pen_anchor"):
                            snapshot["program"] = bind_anchor(
                                snapshot["program"],
                                reference["position"],
                                snapshot["page"],
                            )
                            snapshot["machine"]["pen_anchor_position"] = reference[
                                "position"
                            ]
                            job.pen_position = list(reference["position"])
                        job.estimated_duration_seconds = estimate_seconds(
                            snapshot["program"],
                            snapshot["machine"],
                            reference["position"],
                        )
                        snapshot["position_pending"] = False
                        store.bind_job_snapshot(identifier, snapshot)
                        job.status = "cancelling" if flag.is_set() else "running"
                        store.update_resource("jobs", job.model_dump(mode="json"))
                    touched = True
                    self.machine.send_program(
                        snapshot["machine"],
                        snapshot["program"],
                        submission_id=identifier,
                        on_progress=progress,
                        cancelled=flag.is_set,
                    )
                job.status = "cancelled" if flag.is_set() else "succeeded"
            except ExecutionCancelled as exc:
                job.status = "cancelled"
                job.message = str(exc)
            except ExecutionRejected as exc:
                job.status = "failed"
                job.error = Problem(
                    code="execution_rejected", message=str(exc), retry_advice="refresh"
                )
            except PublicError as exc:
                job.status = "failed"
                job.error = exc.problem
            except Exception as exc:
                # 实机已交给驱动后，异常本身不能证明运动已停止。
                job.status = "interrupted" if touched else "failed"
                job.error = Problem(
                    code="execution_interrupted" if touched else "execution_failed",
                    message=str(exc),
                    retry_advice="query_status",
                )
                logger.exception("任务 %s 执行未完成", identifier)
            finally:
                job.finished_at = store.now()
                job.message = (
                    job.error.message
                    if job.error
                    else ("演练完成" if job.mode == "simulate" else "书写完成")
                )
                with self.lock:
                    store.update_resource("jobs", job.model_dump(mode="json"))
                    if job.status == "interrupted" and job.mode == "execute":
                        self.halted = True
                    if self.owner == ("job", identifier):
                        self._reserve_next()
                    self.cancel_flags.pop(identifier, None)

    def acquire(self, key):
        with self.lock:
            if not key:
                raise PublicError(
                    422, "idempotency_key_required", "需要 Idempotency-Key"
                )
            self._expire()
            persisted = store.find_key("sessions", key, "session")
            if persisted:
                identifier = persisted
                if self.session and self.session.id == identifier:
                    return self.session
                raise PublicError(
                    409, "session_expired", "原控制会话已失效，请使用新去重键"
                )
            if self.owner:
                raise PublicError(409, "machine_busy", "设备已被占用", advice="wait")
            token = self.machine.begin_session()
            if token is None:
                raise PublicError(409, "machine_busy", "设备已有控制者", advice="wait")
            self.session = Session(id="session_" + uuid.uuid4().hex, expires_at="")
            self.session_token = token
            self.owner = ("session", self.session.id)
            self.session_keys[key] = self.session.id
            store.remember_session(key, self.session.id)
            self.deadline = time.monotonic() + 30
            return self.renew(self.session.id)

    def renew(self, identifier):
        with self.lock:
            self._expire()
            if (
                not self.session
                or self.session.id != identifier
                or self.session.status != "active"
            ):
                raise PublicError(409, "session_expired", "控制会话已失效")
            self.deadline = time.monotonic() + 30
            self.session.expires_at = (
                datetime.now(UTC) + timedelta(seconds=30)
            ).isoformat()
            return self.session.model_copy(deep=True)

    def release(self, identifier):
        with self.lock:
            if not self.session or self.session.id != identifier:
                return self.session_history.get(
                    identifier,
                    Session(id=identifier, expires_at=store.now(), status="released"),
                )
            old = self.session.model_copy(deep=True)
            self._release_session("released")
            old.status = "closing" if self.session else "released"
            return old

    def _cancel_pending(self, session):
        for identifier, meta in list(self.pending.items()):
            if meta["session"] == session and not meta["running"]:
                op = self.operation(identifier)
                op.status = "cancelled"
                op.updated_at = store.now()
                store.update_resource("operations", op.model_dump(mode="json"))

    def enqueue_operation(self, kind, payload, key):
        with self.lock:
            body = {"kind": kind, **payload}
            existing, digest = self._key("operations", key, body)
            if existing:
                return self.operation(existing)
            self._expire()
            sid = payload.get("session_id")
            if sid:
                if (
                    not self.session
                    or self.session.id != sid
                    or self.session.status != "active"
                ):
                    raise PublicError(409, "session_expired", "控制会话已失效")
                if len(self.pending) >= 4:
                    raise PublicError(
                        409, "operation_queue_full", "最多等待三次点动", advice="wait"
                    )
            elif self.owner:
                raise PublicError(409, "machine_busy", "设备已被占用", advice="wait")
            if kind in ("command", "firmware") and not sid:
                raise PublicError(
                    409, "control_session_required", "此操作需要手动控制会话"
                )
            if kind == "firmware":
                preview = store.get_preview(payload["preview_id"])
                if not preview:
                    raise PublicError(404, "preview_not_found", "参数预览不存在")
                if preview["context_hash"] != context_hash():
                    raise PublicError(
                        409,
                        "execution_context_changed",
                        "参数预览上下文已改变",
                        advice="reprepare",
                    )
            identifier = "op_" + uuid.uuid4().hex
            op = Operation(
                id=identifier,
                kind=kind,
                status="queued",
                created_at=store.now(),
                updated_at=store.now(),
            )
            store.create_resource(
                "operations", op.model_dump(mode="json"), body, key, digest
            )
            self.pending[identifier] = {"session": sid, "running": False}
            if not sid:
                self.owner = ("operation", identifier)
            self.pool.submit(self._operate, identifier)
            return op

    def _operate(self, identifier):
        with self.lock:
            self._expire()
            op = self.operation(identifier)
            meta = self.pending[identifier]
            if op.status == "cancelled":
                self.pending.pop(identifier, None)
                return
            meta["running"] = True
            op.status = "running"
            op.updated_at = store.now()
            store.update_resource("operations", op.model_dump(mode="json"))
            token = self.session_token if meta["session"] else None
        payload = json.loads(store.get_resource("operations", identifier)["payload"])
        try:
            kind = op.kind
            if (
                self.halted
                and kind in ("command", "firmware")
                and payload.get("type") != "recover"
            ):
                raise PublicError(409, "emergency_active", "急停后需显式恢复设备")
            if kind == "probe":
                result = {"kind": "probe", "ports": self.maintenance.probe()}
            elif kind == "refresh":
                result = {
                    "kind": "refresh",
                    "machine": self._record_machine(
                        self.machine.inspect(session=token)
                    ).model_dump(mode="json"),
                }
            elif kind == "backup":
                raw = self.machine.backup(session=token)
                result = {
                    "kind": "backup",
                    "backup": self.maintenance.backup_info(raw["path"]),
                }
            elif kind == "firmware":
                preview = store.get_preview(payload["preview_id"])
                if preview["context_hash"] != context_hash():
                    raise PublicError(
                        409,
                        "execution_context_changed",
                        "参数预览上下文已改变",
                        advice="reprepare",
                    )
                result = self.maintenance.apply(preview["changes"], token)
                self.snapshot.stale = True
                self.snapshot_time = 0
            else:
                action = payload["type"]
                if action == "cancel_pending":
                    with self.lock:
                        self._cancel_pending(meta["session"])
                    raw = {}
                elif action == "disconnect":
                    self.machine.close_manual_connection()
                    raw = {}
                elif action == "recover":
                    raw = self.machine.recover({}, session=token)
                    self.halted = False
                else:
                    mapping = {"set_origin": "zero", "goto_origin": "goto_zero"}
                    raw = self.machine.jog(
                        {
                            "action": payload["axis"]
                            if action == "jog"
                            else mapping.get(action, action),
                            "dist": payload.get("distance_mm", 0),
                        },
                        session=token,
                    )
                result = {
                    "kind": "command",
                    "action": action,
                    "machine": self._record_machine(raw).model_dump(mode="json")
                    if raw.get("state")
                    else None,
                }
            op.result = DeviceResult.model_validate(result)
            op.status = (
                "interrupted"
                if op.result.unknown
                else "failed"
                if op.result.failed
                else "succeeded"
            )
            if op.status != "succeeded":
                op.error = Problem(
                    code="partial_firmware_update",
                    message="参数未全部确认写入，请查询设备后核对",
                    retry_advice="query_status",
                )
        except PublicError as exc:
            op.status = "failed"
            op.error = exc.problem
        except Exception as exc:
            op.status = (
                "interrupted" if op.kind in ("command", "firmware") else "failed"
            )
            op.error = Problem(
                code="device_operation_failed",
                message=str(exc),
                retry_advice="query_status"
                if op.status == "interrupted"
                else "refresh",
            )
            logger.exception("设备操作 %s 失败", identifier)
        finally:
            with self.lock:
                op.updated_at = store.now()
                store.update_resource("operations", op.model_dump(mode="json"))
                self.pending.pop(identifier, None)
                if op.status != "succeeded" and meta["session"]:
                    self._cancel_pending(meta["session"])
                if self.owner == ("operation", identifier):
                    self.owner = None
                if (
                    self.session
                    and self.session.status == "closing"
                    and not self.pending
                ):
                    self._release_session("released")

    def firmware_preview(self, request):
        try:
            commands = self.maintenance.preview(request.changes)
        except ValueError as exc:
            raise PublicError(422, "invalid_firmware_parameters", str(exc)) from exc
        result = FirmwarePreview(
            id="fw_" + uuid.uuid4().hex,
            changes=request.changes,
            commands=commands,
            context_hash=context_hash(),
        )
        store.save_preview(result.model_dump(mode="json"))
        return result

    def patch_config(self, kind, body, etag):
        with self.lock:
            self._expire()
            if self.owner and kind in ("connection", "calibration"):
                raise PublicError(
                    409,
                    "machine_busy",
                    "执行或控制期间不能更改设备定位配置",
                    advice="wait",
                )
            return configuration.patch(kind, body, etag)

    def emergency(self):
        # 不获取普通仲裁锁，也不进入操作队列。
        self.halted = True
        for flag in list(self.cancel_flags.values()):
            flag.set()
        try:
            sent = self.machine.priority_stop()
        except Exception:
            logger.exception("急停指令发送结果未知")
            sent = False
        with self.lock:
            if self.session:
                self._cancel_pending(self.session.id)
        timestamp = store.now()
        identifier = "op_" + uuid.uuid4().hex
        result = DeviceResult(kind="emergency", command_sent=sent, stop_confirmed=False)
        op = Operation(
            id=identifier,
            kind="emergency",
            status="interrupted",
            created_at=timestamp,
            updated_at=timestamp,
            result=result,
            error=Problem(
                code="stop_unconfirmed",
                message="急停指令已发送，停止状态尚未确认"
                if sent
                else "无活动设备连接，无法确认急停",
                retry_advice="query_status",
            ),
        )
        store.create_resource(
            "operations", op.model_dump(mode="json"), {}, identifier, identifier
        )
        return op
