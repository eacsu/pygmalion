"""确定性的电路整理：网格间距、正交导线、贴近器件的避让标注。"""

import math

from ..schemas.circuit import CircuitElement, Point
from ..writing.layout import char_width_units
from .circuit import component_geometry


def overlaps(a, b, gap=0):
    return (
        a[0] < b[0] + b[2] + gap
        and a[0] + a[2] + gap > b[0]
        and a[1] < b[1] + b[3] + gap
        and a[1] + a[3] + gap > b[1]
    )


def segment_box(a, b, box):
    x, y, w, h = box
    if a[0] == b[0]:
        return x < a[0] < x + w and max(a[1], b[1]) > y and min(a[1], b[1]) < y + h
    return y < a[1] < y + h and max(a[0], b[0]) > x and min(a[0], b[0]) < x + w


def layout_circuit(source: CircuitElement) -> CircuitElement:
    """保留电路拓扑和粗略方位，重排重叠元件；不修改原始输入或机器位置。"""
    e = source.model_copy(deep=True)
    boxes, pins = {}, {}
    origin_x = min(c.x_mm for c in e.circuit.components)
    origin_y = min(c.y_mm for c in e.circuit.components)
    # 以稳定 ID 排序，输入数组次序不影响结果；拥挤元件沿网格寻找最近空位。
    for c in sorted(e.circuit.components, key=lambda c: (c.y_mm, c.x_mm, c.id)):
        (bx, by, bw, bh), anchors = component_geometry(c, e.circuit.standard)
        ox, oy = (
            round((c.x_mm - origin_x) / 2.5) * 2.5,
            round((c.y_mm - origin_y) / 2.5) * 2.5,
        )
        found = False
        for radius in range(81):
            offsets = [
                (dx, dy)
                for dx in range(-radius, radius + 1)
                for dy in range(-radius, radius + 1)
                if max(abs(dx), abs(dy)) == radius
            ]
            offsets.sort(
                key=lambda p: (p[0] * p[0] + p[1] * p[1], abs(p[1]), p[1], p[0])
            )
            for dx, dy in offsets:
                x, y = ox + dx * 5, oy + dy * 5
                box = (x + bx, y + by, bw, bh)
                if not any(overlaps(box, other, 6) for other in boxes.values()):
                    c.x_mm, c.y_mm = x, y
                    boxes[c.id] = box
                    pins[c.id] = {k: (x + v[0], y + v[1]) for k, v in anchors.items()}
                    found = True
                    break
            if found:
                break
        if not found:
            raise ValueError("电路过于拥挤，请拆分电路图")
    for j in e.circuit.junctions:
        j.x_mm -= origin_x
        j.y_mm -= origin_y
    junctions = {j.id: (j.x_mm, j.y_mm) for j in e.circuit.junctions}

    def endpoint(p):
        if p.junction_id:
            return junctions[p.junction_id]
        try:
            return pins[p.component_id][p.pin]
        except KeyError:
            raise ValueError(f"引脚不存在：{p.component_id}.{p.pin}") from None

    segments = []
    for wire in sorted(e.circuit.wires, key=lambda w: w.id):
        a, b = endpoint(wire.start), endpoint(wire.end)
        obstacles = [
            v
            for k, v in boxes.items()
            if k not in {wire.start.component_id, wire.end.component_id}
        ]
        candidates = [[a, (b[0], a[1]), b], [a, (a[0], b[1]), b]]
        xs = sorted(
            {
                a[0] - 5,
                b[0] + 5,
                *[v[0] - 3 for v in obstacles],
                *[v[0] + v[2] + 3 for v in obstacles],
            }
        )
        ys = sorted(
            {
                a[1] - 5,
                b[1] + 5,
                *[v[1] - 3 for v in obstacles],
                *[v[1] + v[3] + 3 for v in obstacles],
            }
        )
        for x in xs:
            candidates.append([a, (x, a[1]), (x, b[1]), b])
        for y in ys:
            candidates.append([a, (a[0], y), (b[0], y), b])

        def cost(pts):
            pairs = list(zip(pts, pts[1:]))
            collisions = sum(
                segment_box(p, q, box) for p, q in pairs for box in obstacles
            )
            length = sum(math.dist(p, q) for p, q in pairs)
            return collisions, length + len(pts) * 2, pts

        best = min(candidates, key=cost)
        clean = [best[0]]
        for p in best[1:]:
            if p != clean[-1]:
                clean.append(p)
        wire.waypoints = [Point(x_mm=x, y_mm=y) for x, y in clean[1:-1]]
        wire.first_axis = "horizontal"
        segments.extend(zip(clean, clean[1:]))
    labels = []
    for c in sorted(e.circuit.components, key=lambda c: c.id):
        text = " ".join(filter(None, [c.reference, c.value]))
        lines = list(filter(None, [text, c.label]))
        if not lines:
            continue
        size = e.label_size_mm
        w = max(sum(char_width_units(ch) * size for ch in line) for line in lines)
        h = len(lines) * (size + 1) - 1
        x, y, bw, bh = boxes[c.id]
        top = (x + (bw - w) / 2, y - h - 1.5, w, h)
        bottom = (x + (bw - w) / 2, y + bh + 1.5, w, h)
        right = (x + bw + 2, y + (bh - h) / 2, w, h)
        left = (x - w - 2, y + (bh - h) / 2, w, h)
        choices = [right, left, top, bottom] if bh > bw else [top, bottom, right, left]

        def label_cost(box):
            return (
                sum(overlaps(box, b, 1) for b in [*boxes.values(), *labels]),
                sum(segment_box(p, q, box) for p, q in segments),
                choices.index(box),
            )

        box = min(choices, key=label_cost)
        labels.append(box)
        c.label_dx_mm = box[0] + w / 2 - (x + bw / 2)
        c.label_dy_mm = box[1] - y + (len(lines) - 1) * (size + 1)
    # 包含所有器件、连接点和标注，统一移入参考框，再等比适配。
    all_boxes = [
        *boxes.values(),
        *labels,
        *[(x, y, 0, 0) for x, y in junctions.values()],
    ]
    points = [p for pair in segments for p in pair]
    left = min([b[0] for b in all_boxes] + [p[0] for p in points]) - 4
    top = min([b[1] for b in all_boxes] + [p[1] for p in points]) - 4
    right = max([b[0] + b[2] for b in all_boxes] + [p[0] for p in points]) + 4
    bottom = max([b[1] + b[3] for b in all_boxes] + [p[1] for p in points]) + 4
    for item in [
        *e.circuit.components,
        *e.circuit.junctions,
        *[p for w in e.circuit.wires for p in w.waypoints],
    ]:
        item.x_mm -= left
        item.y_mm -= top
    fitted = min(e.width_mm / (right - left), e.height_mm / (bottom - top))
    if fitted < 0.05:
        raise ValueError("排版范围过大，请增大参考框或拆分电路图")
    e.scale = min(20, fitted)
    return CircuitElement.model_validate(e.model_dump())
