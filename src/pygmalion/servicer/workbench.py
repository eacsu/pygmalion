"""文档变换，不创建任务或持有设备。"""

from ..schemas.canvas import FitRequest, Table
from ..writing.canvas import fit_table, prepare_canvas
from .errors import ServiceError


def fit_document_table(data: FitRequest):
    table = next(
        (
            e
            for e in data.document.elements
            if e.id == data.element_id and isinstance(e, Table)
        ),
        None,
    )
    if table is None:
        raise ServiceError("invalid", {"error": "未找到表格"})
    try:
        fitted, diagnostics = fit_table(table)
        if not diagnostics:
            document = data.document.model_copy(update={"elements": [fitted]})
            prepared, _ = prepare_canvas(document)
            diagnostics = [d for d in prepared.diagnostics if d["code"] == "overflow"]
        return {
            "table": (table if diagnostics else fitted).model_dump(),
            "diagnostics": diagnostics,
            "success": not diagnostics,
        }
    except ValueError as exc:
        raise ServiceError("invalid", {"error": str(exc)})


def import_vector(data):
    from ..drawing.svg import import_svg

    try:
        result = import_svg(data.source)
        ratio = min(1, 170 / result["width_mm"], 257 / result["height_mm"])
        result["width_mm"] *= ratio
        result["height_mm"] *= ratio
        return {"name": data.name, **result}
    except ValueError as exc:
        raise ServiceError("invalid", {"error": str(exc)})
