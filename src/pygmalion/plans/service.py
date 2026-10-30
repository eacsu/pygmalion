"""内容准备只产生冻结方案，不获取设备控制权。"""

import copy
import hashlib
import json
import uuid

from ..config import CONFIG
from ..execution import repository
from ..fonts import registry
from ..schemas.canvas import CanvasDocument
from ..schemas.public import Diagnostic, Plan, SoftwareSettings
from ..writing import canvas
from ..writing.canvas import prepare_canvas


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def context_hash():
    return fingerprint(
        {
            "page": CONFIG["page"],
            "connection": {k: CONFIG["machine"][k] for k in ("port", "baud")},
            "firmware_context": CONFIG.get("device_context", {}),
        }
    )


def create_plan(document: CanvasDocument):
    identifier = "plan_" + uuid.uuid4().hex
    diagnostics = []
    code = []
    svg = '<svg xmlns="http://www.w3.org/2000/svg"/>'
    strokes = cells = 0
    machine = copy.deepcopy(CONFIG["machine"])
    try:
        prepared, _ = prepare_canvas(document)
        code, svg = prepared.gcode, prepared.svg
        strokes, cells = prepared.strokes, prepared.cells
        diagnostics = [Diagnostic.model_validate(item) for item in prepared.diagnostics]
        if not prepared.can_print and not diagnostics:
            diagnostics = [Diagnostic(code="empty_content", message="没有可绘制的内容")]
    except ValueError as exc:
        diagnostics = [Diagnostic(code="font_unavailable", message=str(exc))]
    result = Plan(
        id=identifier,
        status="blocked" if diagnostics else "ready",
        created_at=repository.now(),
        document=document,
        diagnostics=diagnostics,
        preview_url=f"/api/v1/plans/{identifier}/preview",
        context_hash=context_hash(),
        software=SoftwareSettings.model_validate(
            {k: machine[k] for k in SoftwareSettings.model_fields}
        ),
        fonts=[font.id for font in registry.discover(canvas.ROOT)],
        strokes=strokes,
        cells=cells,
    )
    repository.put_plan(
        identifier,
        {
            "plan": result.model_dump(mode="json"),
            "program": code,
            "svg": svg,
            "machine": machine,
            "font_sources": {
                font.id: hashlib.sha256(font.dataset_path.read_bytes()).hexdigest()
                for font in registry.discover(canvas.ROOT)
            },
            "page": copy.deepcopy(CONFIG["page"]),
        },
    )
    return result


def bind_anchor(program, position, page):
    """冻结轨迹以定位点为零；只做一次刚性平移，不重新排版。"""
    import re

    pattern = re.compile(r"(?P<axis>[XY])(?P<value>[-+]?\d+(?:\.\d+)?)")
    output = []
    for line in program:
        if line.startswith(("G0 X", "G1 X")):
            line = pattern.sub(
                lambda m: (
                    f"{m['axis']}{float(m['value']) + position[0 if m['axis'] == 'X' else 1]:.3f}"
                ),
                line,
            )
            coords = {m["axis"]: float(m["value"]) for m in pattern.finditer(line)}
            if page.get("fixed_grid_origin") and "X" in coords and "Y" in coords:
                x = -coords["X"] if page.get("invert_x", True) else coords["X"]
                y = -coords["Y"] if page.get("invert_y", False) else coords["Y"]
                if page.get("axes_swapped", True):
                    x, y = y, x
                if not (
                    page.get("paper_min_x_mm", -100) - 0.001
                    <= x
                    <= page.get("grid_width_mm", 190) + 0.001
                    and page.get("paper_min_y_mm", -50) - 0.001
                    <= y
                    <= page.get("grid_height_mm", 280) + 0.001
                ):
                    raise ValueError("笔头定位后的内容超出写字盘范围")
        output.append(line)
    return output
