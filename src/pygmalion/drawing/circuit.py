"""Schemdraw 标准符号 → 毫米中心线；结构和引脚始终保留。"""

import math
from dataclasses import dataclass
from functools import lru_cache
from xml.etree import ElementTree as ET

import schemdraw
import schemdraw.elements as elm
from schemdraw.segments import Segment

from ..schemas.canvas import Vector
from ..schemas.circuit import CircuitElement, Component
from ..writing.handwriting import JitterConfig
from ..writing.layout import char_width_units
from ..writing.models import PlacedGlyph, Stroke
from ..writing.prepare import _glyph_source
from ..writing.render import render_glyphs
from .svg import import_svg, vector_strokes

UNIT = 5.0
CATALOG = {
    "resistor": ("电阻", elm.ResistorIEC),
    "capacitor": ("电容", elm.Capacitor),
    "capacitor_polar": ("有极性电容", elm.Capacitor2),
    "inductor": ("电感", elm.Inductor),
    "voltage_source": ("直流电压源", elm.SourceV),
    "current_source": ("电流源", elm.SourceI),
    "ac_source": ("交流电源", elm.SourceSin),
    "ground": ("接地", elm.Ground),
    "diode": ("二极管", elm.Diode),
    "zener": ("稳压二极管", elm.Zener),
    "led": ("发光二极管", elm.LED),
    "npn": ("NPN 三极管", elm.BjtNpn),
    "pnp": ("PNP 三极管", elm.BjtPnp),
    "nmos": ("N 沟道 MOS 管", elm.NFet),
    "pmos": ("P 沟道 MOS 管", elm.PFet),
    "opamp": ("运算放大器", elm.Opamp),
    "switch": ("开关", elm.Switch),
}


@lru_cache(maxsize=512)
def symbol_geometry(kind, angle=0, length=15.0, standard="IEC"):
    cls = CATALOG[kind][1]
    if kind == "resistor" and standard == "ANSI":
        cls = elm.Resistor
    drawing = schemdraw.Drawing(canvas="svg", show=False)
    element = cls().at((0, 0)).theta(-angle)
    if kind == "capacitor_polar":
        # Schemdraw 的 polar=True 使用字体文本；改为相同位置的单线加号。
        element.segments.extend(
            [
                Segment([(-0.306, 0.18), (-0.126, 0.18)]),
                Segment([(-0.216, 0.09), (-0.216, 0.27)]),
            ]
        )
    if isinstance(element, elm.Element2Term):
        element.length(length / UNIT)
    drawing.add(element)
    # 只处理本进程由固定符号目录产生的 SVG，不放宽用户 SVG 导入规则。
    root = ET.fromstring(drawing.get_imagedata("svg"))
    for node in root.iter():
        style = node.attrib.pop("style", "")
        for declaration in style.split(";"):
            if ":" not in declaration:
                continue
            key, value = (part.strip() for part in declaration.split(":", 1))
            if key in {
                "stroke",
                "fill",
                "stroke-width",
                "stroke-linecap",
                "stroke-linejoin",
                "stroke-miterlimit",
                "opacity",
            }:
                node.set(key, value)
            elif key == "stroke-dasharray" and value not in {"-", "none", ""}:
                raise ValueError("电路符号包含不支持的虚线")
    data = import_svg(ET.tostring(root, encoding="unicode"))
    box = element.get_bbox(transform=True)
    bounds = (
        box.xmin * UNIT,
        -box.ymax * UNIT,
        max(0.25, (box.xmax - box.xmin) * UNIT),
        max(0.25, (box.ymax - box.ymin) * UNIT),
    )
    anchors = {
        key: (float(p.x) * UNIT, -float(p.y) * UNIT)
        for key, p in element.absanchors.items()
    }
    return data, bounds, anchors


def pin_names(kind):
    if kind in {"npn", "pnp"}:
        return {"base", "collector", "emitter"}
    if kind in {"nmos", "pmos"}:
        return {"gate", "source", "drain", "bulk"}
    if kind == "opamp":
        return {"in1", "in2", "out", "vd", "vs"}
    if kind == "ground":
        return {"start"}
    return {"start", "end"}


def chip_geometry(component: Component):
    """引脚按每侧的声明顺序等距排列；坐标以芯片中心为原点。"""
    width = component.length_mm
    counts = {side: sum(p.side == side for p in component.chip_pins) for side in ("left", "right", "top", "bottom")}
    height = max(18.0, 6.0 * max(counts["left"], counts["right"]) + 6.0)
    width = max(width, 6.0 * max(counts["top"], counts["bottom"]) + 6.0)
    anchors = {}
    for side, count in counts.items():
        side_pins = [p for p in component.chip_pins if p.side == side]
        for index, pin in enumerate(side_pins, 1):
            fraction = index / (count + 1)
            anchors[pin.name] = {
                "left": (-width / 2 - 4, -height / 2 + height * fraction),
                "right": (width / 2 + 4, -height / 2 + height * fraction),
                "top": (-width / 2 + width * fraction, -height / 2 - 4),
                "bottom": (-width / 2 + width * fraction, height / 2 + 4),
            }[side]
    def rotate(point):
        x, y = point
        angle = math.radians(component.angle)
        return (x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle))
    anchors = {name: rotate(point) for name, point in anchors.items()}
    corners = [rotate(p) for p in [(-width / 2, -height / 2), (width / 2, -height / 2), (width / 2, height / 2), (-width / 2, height / 2)]]
    bounds = (min(p[0] for p in corners), min(p[1] for p in corners), max(p[0] for p in corners) - min(p[0] for p in corners), max(p[1] for p in corners) - min(p[1] for p in corners))
    return bounds, anchors, corners


def component_geometry(component: Component, standard="IEC"):
    if component.kind == "chip":
        bounds, anchors, _ = chip_geometry(component)
        return bounds, anchors
    _, bounds, anchors = symbol_geometry(component.kind, component.angle, component.length_mm, standard)
    return bounds, anchors


def list_symbols():
    return {
        "symbols": [
            {
                "kind": kind,
                "name": name,
                "pins": sorted(pin_names(kind) & symbol_geometry(kind)[2].keys()),
                "default_length_mm": 15,
            }
            for kind, (name, _) in CATALOG.items()
        ] + [
            {"kind": "chip", "name": "多引脚芯片", "pins": [], "default_length_mm": 30}
        ],
        "units": "mm",
        "standards": ["IEC", "ANSI"],
    }


@dataclass
class CircuitDrawing:
    strokes: list[Stroke]
    layout: dict
    diagnostics: list[dict]


def render_circuit(element: CircuitElement) -> CircuitDrawing:
    strokes, diagnostics, components, wires, label_boxes = [], [], [], [], []
    pins = {}
    used = set()
    refs = set()
    scale = element.scale

    def xy(x, y):
        return element.x_mm + x * scale, element.y_mm + y * scale

    def issue(code, message, target, severity="warning"):
        diagnostics.append(
            {
                "code": code,
                "message": message,
                "severity": severity,
                "element_id": element.id,
                "details": {"target_id": target},
            }
        )

    source = None

    def label(text, x, y, target):
        nonlocal source
        if not text:
            return
        if source is None:
            source = _glyph_source(element.font or None)
        size = element.label_size_mm * scale
        width = sum(char_width_units(ch) * size for ch in text)
        xx, yy = xy(x, y)
        cursor = xx - width / 2
        glyphs = []
        for ch in text:
            advance = char_width_units(ch) * size
            if not ch.isspace():
                glyphs.append(
                    PlacedGlyph(
                        ch,
                        cursor + advance / 2,
                        yy + size / 2,
                        size,
                        scale_x=advance / size,
                    )
                )
            cursor += advance
        paths, missing = render_glyphs(glyphs, source, JitterConfig(enabled=False))
        strokes.extend(paths)
        if missing:
            issue("missing", "电路标注缺字：" + "、".join(missing), target, "error")
        label_boxes.append(
            {
                "x_mm": xx - width / 2,
                "y_mm": yy,
                "width_mm": width,
                "height_mm": size,
                "target_id": target,
            }
        )

    for component in element.circuit.components:
        bounds, anchors = component_geometry(component, element.circuit.standard)
        bx, by, bw, bh = bounds
        x, y = xy(component.x_mm + bx, component.y_mm + by)
        if component.kind == "chip":
            _, _, corners = chip_geometry(component)
            strokes.append(Stroke([xy(component.x_mm + px, component.y_mm + py) for px, py in [*corners, corners[0]]]))
            for pin in component.chip_pins:
                px, py = anchors[pin.name]
                direction = {"left": (4, 0), "right": (-4, 0), "top": (0, 4), "bottom": (0, -4)}[pin.side]
                angle = math.radians(component.angle)
                dx = direction[0] * math.cos(angle) - direction[1] * math.sin(angle)
                dy = direction[0] * math.sin(angle) + direction[1] * math.cos(angle)
                inner = (px + dx, py + dy)
                strokes.append(Stroke([xy(component.x_mm + px, component.y_mm + py), xy(component.x_mm + inner[0], component.y_mm + inner[1])]))
                label(pin.label or pin.name, component.x_mm + inner[0] + dx * 0.7, component.y_mm + inner[1] + dy * 0.7 - 1, component.id)
        else:
            data, _, _ = symbol_geometry(component.kind, component.angle, component.length_mm, element.circuit.standard)
            vector = Vector(id=component.id, x_mm=x, y_mm=y, width_mm=bw * scale, height_mm=bh * scale, **{key: value for key, value in data.items() if key not in {"x_mm", "y_mm", "width_mm", "height_mm"}})
            strokes.extend(vector_strokes(vector))
        component_pins = {
            name: {
                "x_mm": xy(component.x_mm + px, component.y_mm + py)[0],
                "y_mm": xy(component.x_mm + px, component.y_mm + py)[1],
            }
            for name, (px, py) in anchors.items()
            if component.kind == "chip" or name in pin_names(component.kind)
        }
        pins[component.id] = component_pins
        components.append(
            {
                "id": component.id,
                "x_mm": x,
                "y_mm": y,
                "width_mm": bw * scale,
                "height_mm": bh * scale,
                "pins": component_pins,
            }
        )
        if component.reference:
            if component.reference in refs:
                issue(
                    "duplicate_reference",
                    "元件编号重复：" + component.reference,
                    component.id,
                )
            refs.add(component.reference)
        cx, cy = (
            component.x_mm + bx + bw / 2 + component.label_dx_mm,
            component.y_mm + by + component.label_dy_mm,
        )
        lines = list(
            filter(
                None,
                [
                    " ".join(filter(None, [component.reference, component.value])),
                    component.label,
                ],
            )
        )
        cy -= (len(lines) - 1) * (element.label_size_mm + 1)
        for offset, text in enumerate(lines):
            label(text, cx, cy + offset * (element.label_size_mm + 1), component.id)

    junctions = {j.id: xy(j.x_mm, j.y_mm) for j in element.circuit.junctions}
    for junction in element.circuit.junctions:
        x, y = junctions[junction.id]
        radius = 0.45 * scale
        # 明确连接点画实心点；普通导线交叉不产生连接点。
        strokes.append(
            Stroke(
                [
                    (
                        x + radius * math.cos(i * math.pi / 8),
                        y + radius * math.sin(i * math.pi / 8),
                    )
                    for i in range(17)
                ]
            )
        )
        for offset in range(-3, 4):
            dy = radius * offset / 4
            half = math.sqrt(radius * radius - dy * dy)
            strokes.append(Stroke([(x - half, y + dy), (x + half, y + dy)]))
        label(junction.label, junction.x_mm, junction.y_mm - 5, junction.id)

    def endpoint(endpoint, wire_id):
        if endpoint.junction_id:
            return junctions[endpoint.junction_id]
        pin = pins.get(endpoint.component_id, {}).get(endpoint.pin)
        if pin is None:
            issue(
                "invalid_pin",
                f"引脚不存在：{endpoint.component_id}.{endpoint.pin}",
                wire_id,
                "error",
            )
            return None
        used.add((endpoint.component_id, endpoint.pin))
        return pin["x_mm"], pin["y_mm"]

    for wire in element.circuit.wires:
        start, end = endpoint(wire.start, wire.id), endpoint(wire.end, wire.id)
        if start is None or end is None:
            continue
        points = [start]
        for target in [*[xy(p.x_mm, p.y_mm) for p in wire.waypoints], end]:
            prev = points[-1]
            if prev[0] != target[0] and prev[1] != target[1]:
                points.append(
                    (target[0], prev[1])
                    if wire.first_axis == "horizontal"
                    else (prev[0], target[1])
                )
            if points[-1] != target:
                points.append(target)
        if len(points) < 2:
            issue("zero_wire", "导线端点重合", wire.id)
        else:
            strokes.append(Stroke(points))
        wires.append(
            {"id": wire.id, "points": [{"x_mm": x, "y_mm": y} for x, y in points]}
        )
    for component in element.circuit.components:
        relevant = list(pins[component.id]) if component.kind == "chip" else [
            p
            for p in pins[component.id]
            if p
            in {
                "start",
                "end",
                "base",
                "collector",
                "emitter",
                "gate",
                "source",
                "drain",
                "in1",
                "in2",
                "out",
            }
        ]
        if relevant and any((component.id, p) not in used for p in relevant):
            issue(
                "unconnected_pin",
                "存在未连接引脚：" + (component.reference or component.id),
                component.id,
            )
    for uncertainty in element.circuit.uncertainties:
        issue(
            "unconfirmed",
            "待确认：" + uncertainty.message,
            uncertainty.target_id,
            "error",
        )
    for i, a in enumerate(label_boxes):
        for b in [*label_boxes[i + 1 :], *components]:
            if b.get("target_id", b.get("id")) == a["target_id"]:
                continue
            if (
                a["x_mm"] < b["x_mm"] + b["width_mm"]
                and a["x_mm"] + a["width_mm"] > b["x_mm"]
                and a["y_mm"] < b["y_mm"] + b["height_mm"]
                and a["y_mm"] + a["height_mm"] > b["y_mm"]
            ):
                issue("label_overlap", "电路标注与其他内容重叠", a["target_id"])
                break
    if sum(len(s.points) for s in strokes) > 100000:
        raise ValueError("电路图过于复杂，请拆分为多个电路元素")
    return CircuitDrawing(
        strokes,
        {
            "element_id": element.id,
            "regions": [],
            "components": components,
            "wires": wires,
            "labels": label_boxes,
        },
        diagnostics,
    )
