"""软件配置的严格整批更新及并发前置条件。"""

from pydantic import ValidationError

from .. import config
from ..machine.connection import normalize_port
from ..plans.service import fingerprint
from ..schemas.canvas import EditorDefaults
from ..schemas.public import CalibrationSettings, ConnectionSettings, SoftwareSettings
from .public_errors import PublicError

MODELS = {
    "software": SoftwareSettings,
    "calibration": CalibrationSettings,
    "editor": EditorDefaults,
    "connection": ConnectionSettings,
}
SECTIONS = {
    "software": "machine",
    "calibration": "page",
    "editor": "editor",
    "connection": "machine",
}


def read(kind):
    model = MODELS[kind]
    raw = config.CONFIG.get(SECTIONS[kind], {})
    values = model.model_validate(
        {key: raw[key] for key in model.model_fields if key in raw}
    )
    result = {
        "values": values.model_dump(mode="json"),
        "etag": '"' + fingerprint(values.model_dump(mode="json")) + '"',
    }
    if kind == "software":
        properties = model.model_json_schema()["properties"]
        result["fields"] = [
            {
                "label": spec["title"],
                "unit": spec["unit"],
                "step": spec["step"],
                "help": spec.get("description", ""),
                "key": key,
                "min": spec["minimum"],
                "max": spec.get("maximum"),
                "value": result["values"][key],
            }
            for key, spec in properties.items()
        ]
    if kind == "calibration":
        result["paper_presets"] = config.PAPER_PRESETS
    return result


def patch(kind, data, etag):
    if etag is None:
        raise PublicError(428, "precondition_required", "更新配置需要 If-Match")
    with config._SAVE_LOCK:
        current = read(kind)
        if etag != current["etag"]:
            raise PublicError(
                412, "configuration_changed", "配置已被其他调用者修改", advice="refresh"
            )
        supplied = data.model_dump(exclude_unset=True)
        if not supplied:
            raise PublicError(422, "empty_update", "没有要保存的字段")
        try:
            values = (
                MODELS[kind]
                .model_validate({**current["values"], **supplied})
                .model_dump(mode="json")
            )
            if kind == "connection":
                values["port"] = normalize_port(values["port"])
        except (ValidationError, ValueError) as exc:
            raise PublicError(422, "invalid_configuration", str(exc)) from exc
        try:
            config.save_section(SECTIONS[kind], values)
        except OSError as exc:
            raise PublicError(
                503, "configuration_unavailable", "配置保存失败，请重试"
            ) from exc
        return read(kind)
