"""离线轮廓字体实验转换：栅格细化、保留骨架边的路径分解和 Parquet 发布。"""

import hashlib
import heapq
import json
import logging
import math
import shutil
from pathlib import Path

import cv2
import numpy as np
from datasets import Dataset
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont
from pyarrow import parquet

from .dataset import load_parquet_font

logger = logging.getLogger(__name__)


def thin(mask):
    """Zhang-Suen 二阶段细化；不删除孤立点或连接端点。"""
    image = np.pad(np.asarray(mask, dtype=bool), 1)
    for _ in range(max(image.shape)):
        changed = False
        for phase in (0, 1):
            p = [
                image[:-2, 1:-1],
                image[:-2, 2:],
                image[1:-1, 2:],
                image[2:, 2:],
                image[2:, 1:-1],
                image[2:, :-2],
                image[1:-1, :-2],
                image[:-2, :-2],
            ]
            neighbors = sum(a.astype(np.uint8) for a in p)
            transitions = sum(
                (~a & b).astype(np.uint8) for a, b in zip(p, p[1:] + p[:1])
            )
            if phase == 0:
                corner = ~(p[0] & p[2] & p[4]) & ~(p[2] & p[4] & p[6])
            else:
                corner = ~(p[0] & p[2] & p[6]) & ~(p[0] & p[4] & p[6])
            remove = (
                image[1:-1, 1:-1]
                & (neighbors >= 2)
                & (neighbors <= 6)
                & (transitions == 1)
                & corner
            )
            if remove.any():
                image[1:-1, 1:-1][remove] = False
                changed = True
        if not changed:
            return image[1:-1, 1:-1]
    raise ValueError("骨架细化未收敛")


def skeleton_paths(mask, optimize=False):
    """覆盖全部骨架边；优化时允许有限回描，虚边始终只用于抬笔。"""
    nodes = set(map(tuple, np.argwhere(mask)))
    adjacency = {p: [] for p in nodes}
    edges = []
    for y, x in sorted(nodes):
        for dy, dx in [(0, 1), (1, -1), (1, 0), (1, 1)]:
            q = (y + dy, x + dx)
            if q not in nodes:
                continue
            # 正交已连通时不再增加像素对角边，避免三角形伪回路。
            if dy and dx and ((y, x + dx) in nodes or (y + dy, x) in nodes):
                continue
            eid = len(edges)
            edges.append(((y, x), q))
            adjacency[(y, x)].append((q, eid))
            adjacency[q].append(((y, x), eid))
    virtual_ids = set()
    # 短距离沿已有骨架回描，换取少一次抬落笔；总回描不超过原线长的 15%。
    original_length = sum(math.dist(a, b) for a, b in edges)
    extra_budget = original_length * 0.15
    limit = max(mask.shape) * 0.12
    remaining = set(nodes)
    paths = []
    while remaining:
        root = min(remaining)
        component = {root}
        todo = [root]
        while todo:
            for q, _ in adjacency[todo.pop()]:
                if q not in component:
                    component.add(q)
                    todo.append(q)
        remaining -= component
        if not adjacency[root]:
            paths.append([(root[1], root[0])] * 2)
            continue
        odd = sorted(p for p in component if len(adjacency[p]) % 2)
        if optimize and len(odd) > 2:
            odd_set = set(odd)
            candidates = []
            for a in odd:
                distances = {a: 0.0}
                parents = {}
                heap = [(0.0, a)]
                while heap:
                    distance, p = heapq.heappop(heap)
                    if distance != distances[p]:
                        continue
                    if p in odd_set and p > a:
                        route = [p]
                        while route[-1] != a:
                            route.append(parents[route[-1]])
                        candidates.append((distance, a, p, tuple(reversed(route))))
                    for q, _ in adjacency[p]:
                        cost = distance + math.dist(p, q)
                        if cost <= limit and cost < distances.get(q, float("inf")):
                            distances[q] = cost
                            parents[q] = p
                            heapq.heappush(heap, (cost, q))
            for distance, a, b, route in sorted(candidates):
                if len(odd_set) <= 2:
                    break
                if a not in odd_set or b not in odd_set or distance > extra_budget:
                    continue
                for p, q in zip(route, route[1:]):
                    eid = len(edges)
                    edges.append((p, q))
                    adjacency[p].append((q, eid))
                    adjacency[q].append((p, eid))
                extra_budget -= distance
                odd_set.remove(a)
                odd_set.remove(b)
            odd = sorted(odd_set)
        while odd:
            a = odd.pop(0)
            b = min(odd, key=lambda p: ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2, p))
            odd.remove(b)
            eid = len(edges)
            virtual_ids.add(eid)
            edges.append((a, b))
            adjacency[a].append((b, eid))
            adjacency[b].append((a, eid))
        stack = [(root, None)]
        tour = []
        used = set()
        while stack:
            p, _ = stack[-1]
            while adjacency[p] and adjacency[p][-1][1] in used:
                adjacency[p].pop()
            if adjacency[p]:
                q, eid = adjacency[p].pop()
                used.add(eid)
                stack.append((q, eid))
            else:
                tour.append(stack.pop())
        tour.reverse()
        steps = [(tour[i - 1][0], tour[i][0], tour[i][1]) for i in range(1, len(tour))]
        virtual = next((i for i, s in enumerate(steps) if s[2] in virtual_ids), None)
        if virtual is not None:
            steps = steps[virtual + 1 :] + steps[: virtual + 1]
        path = []
        for a, b, eid in steps:
            if eid in virtual_ids:
                if len(path) > 1:
                    paths.append(path)
                path = []
            else:
                if not path:
                    path = [(a[1], a[0])]
                path.append((b[1], b[0]))
        if len(path) > 1:
            paths.append(path)
    return paths


def glyph_paths(font, ch, pixels=256, optimize=False):
    box = font.getbbox(ch)
    if box is None:
        return [], 0
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return [], 0
    if max(x1 - x0, y1 - y0) > pixels * 4:
        raise ValueError("字体字形边界异常，超过采样尺寸四倍")
    image = Image.new("L", (x1 - x0 + 16, y1 - y0 + 16), 0)
    ImageDraw.Draw(image).text(
        (8 - x0, 8 - y0), ch, font=font, fill=255, stroke_width=0
    )
    mask = np.asarray(image) >= 128
    skeleton = thin(mask)
    paths = skeleton_paths(skeleton, optimize)
    simplified = []
    for p in paths:
        if len(p) > 2:
            closed = p[0] == p[-1]
            q = (
                cv2.approxPolyDP(
                    np.array(p, dtype=np.float32).reshape(-1, 1, 2),
                    0.9 if optimize else 0.65,
                    closed,
                )
                .reshape(-1, 2)
                .tolist()
            )
            if closed and q and q[0] != q[-1]:
                q.append(q[0])
            if len(q) >= 2:
                p = q
        simplified.append(p)
    if optimize:
        simplified = order_paths(simplified)
    return simplified, int(skeleton.sum())


def order_paths(paths):
    """仅用于无真实笔顺的轮廓转换字形；不跨字、不跨空白落笔连接。"""
    if not paths:
        return []
    remaining = list(paths)
    ordered = []
    xs, ys = zip(*(p for path in paths for p in path))
    cursor = (min(xs), (min(ys) + max(ys)) / 2)
    while remaining:
        _, index, reverse = min(
            (math.dist(cursor, p[-1] if reverse else p[0]), i, reverse)
            for i, p in enumerate(remaining)
            for reverse in (False, True)
        )
        path = remaining.pop(index)
        if reverse:
            path = list(reversed(path))
        ordered.append(path)
        cursor = path[-1]
    return ordered


def convert_outline(
    source: Path,
    license_file: Path,
    output: Path,
    characters: str = "",
    pixels: int = 256,
    optimize: bool = False,
):
    if output.exists():
        raise ValueError("输出目录已存在，不能覆盖")
    if not 96 <= pixels <= 512:
        raise ValueError("采样尺寸必须为 96–512")
    if source.stat().st_size > 50_000_000:
        raise ValueError("字体最大 50 MB")
    license_text = license_file.read_text(encoding="utf-8")
    if "SIL OPEN FONT LICENSE" not in license_text:
        raise ValueError("请提供原字体完整 OFL 许可")
    with TTFont(source) as tt:
        cmap = tt.getBestCmap() or {}
        family = tt["name"].getDebugName(1) or source.stem
    requested = (
        list(dict.fromkeys(characters))
        if characters
        else [
            chr(n)
            for n in sorted(cmap)
            if 33 <= n <= 126
            or 0x3000 <= n <= 0x303F
            or 0x4E00 <= n <= 0x9FFF
            or 0xFF01 <= n <= 0xFF5E
        ]
    )
    font = ImageFont.truetype(str(source), pixels)
    rows = []
    skipped = []
    metrics = []
    for index, ch in enumerate(requested):
        if ch.isspace():
            continue
        if ord(ch) not in cmap or cmap[ord(ch)] == ".notdef":
            skipped.append(ch)
            continue
        paths, pixel_count = glyph_paths(font, ch, pixels, optimize)
        if not paths:
            skipped.append(ch)
            continue
        xs, ys = zip(*(p for path in paths for p in path))
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        factor = 9000 / max(1, max(xs) - min(xs), max(ys) - min(ys))
        normalized = [
            [(round((x - cx) * factor), round((y - cy) * factor)) for x, y in path]
            for path in paths
        ]
        rows.append(
            dict(
                char=ch,
                lengths=[len(p) for p in normalized],
                x=[x for p in normalized for x, y in p],
                y=[y for p in normalized for x, y in p],
                preserve_origin=True,
            )
        )
        metrics.append(
            dict(
                character=ch,
                paths=len(paths),
                points=sum(map(len, paths)),
                skeleton_pixels=pixel_count,
            )
        )
        if (index + 1) % 100 == 0:
            logger.info("已转换 %s/%s 字形", index + 1, len(requested))
    if not rows:
        raise ValueError("没有可转换字形")
    report = dict(
        source_family=family,
        source_file=source.name,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        license_sha256=hashlib.sha256(license_file.read_bytes()).hexdigest(),
        characters=len(rows),
        pixels=pixels,
        skipped=skipped,
        algorithm="Zhang-Suen + bounded skeleton retrace + Euler trails + RDP 0.9px + local ordering"
        if optimize
        else "Zhang-Suen + Euler trails + RDP 0.65px",
        optimized=optimize,
        experimental=True,
        stroke_order="图遍历，不是真实书写笔顺",
        metrics=metrics,
    )
    pending = output.with_name(output.name + ".building")
    pending.mkdir(parents=True, exist_ok=False)
    try:
        parquet.write_table(
            Dataset.from_list(rows).data.table,
            pending / "train.parquet",
            compression="zstd",
        )
        load_parquet_font(pending / "train.parquet")
        shutil.copyfile(license_file, pending / "OFL.txt")
        (pending / "characters.txt").write_text(
            "".join(r["char"] for r in rows), encoding="utf-8"
        )
        (pending / "provenance.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (pending / "README.md").write_text(
            f"# 行意单线 · 实验转换\n\n源字体：{family}；文件：{source.name}。这是改名后的中心线派生字库，沿用 OFL-1.1，完整许可见 OFL.txt，源文件哈希见 provenance.json。\n\n轮廓细化与图遍历只能恢复形状，不能恢复人的笔顺和自然连笔；部分交叉、细节及笔画方向可能不合理。未作实机验证，默认字体未改变。\n",
            encoding="utf-8",
        )
        pending.rename(output)
    except Exception:
        shutil.rmtree(pending)
        raise
    return report
