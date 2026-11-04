"""电路渲染服务，不创建任务或访问设备。"""

from ..drawing.circuit import list_symbols, render_circuit
from ..drawing.circuit_layout import layout_circuit
from ..schemas.circuit import CircuitElement
from ..writing.models import PageConfig
from ..writing.preview import strokes_to_svg
from .errors import ServiceError


def symbols():
    return list_symbols()


def layout(element: CircuitElement):
    try:
        return render(layout_circuit(element))
    except ValueError as exc:
        raise ServiceError("invalid_circuit", {"error": str(exc)}) from exc


def render(element: CircuitElement):
    try:
        result = render_circuit(element)
        xs = [
            element.x_mm,
            element.x_mm + element.width_mm,
            *[x for s in result.strokes for x, y in s.points],
        ]
        ys = [
            element.y_mm,
            element.y_mm + element.height_mm,
            *[y for s in result.strokes for x, y in s.points],
        ]
        left, top = min(xs), min(ys)
        width, height = max(xs) - left, max(ys) - top
        svg = strokes_to_svg(
            result.strokes, PageConfig(width_mm=width, height_mm=height), bg="none"
        )
        svg = svg.replace(
            f'viewBox="0 0 {width:g} {height:g}"',
            f'viewBox="{left:g} {top:g} {width:g} {height:g}"',
        )
        return {
            "element": element,
            "svg": svg,
            "layout": result.layout,
            "diagnostics": result.diagnostics,
        }
    except ValueError as exc:
        raise ServiceError("invalid_circuit", {"error": str(exc)}) from exc
