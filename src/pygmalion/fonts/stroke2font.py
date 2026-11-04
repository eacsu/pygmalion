"""离线导入 Stroke2Font 行楷轨迹；保留原有分笔和方向，不运行上游代码。"""

import hashlib
import json
import math
import shutil
from pathlib import Path

from datasets import Dataset
from pyarrow import parquet

from .dataset import load_parquet_font

SOURCE = "https://github.com/aylqs2025/stroke2font"


def convert(source: Path, license_file: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("输出目录已存在，不能覆盖")
    if source.stat().st_size > 20_000_000:
        raise ValueError("轨迹 JSON 不能超过 20 MB")
    raw = source.read_bytes()
    entries = json.loads(raw)
    if not isinstance(entries, list) or not entries or len(entries) > 10000:
        raise ValueError("需要非空的 Stroke2Font 字形数组，最多 10000 字形")
    license_text = license_file.read_text(encoding="utf-8")
    if "MIT License" not in license_text or "Copyright" not in license_text:
        raise ValueError("请提供上游完整 MIT LICENSE 文件")
    rows, seen, duplicates = [], set(), []
    for index, entry in enumerate(entries):
        ch = entry.get("character") if isinstance(entry, dict) else None
        if not isinstance(ch, str) or len(ch) != 1 or ch.isspace():
            raise ValueError(f"第 {index} 条记录缺少单字符标签")
        strokes = entry.get("strokes")
        if not isinstance(strokes, list) or not strokes or len(strokes) > 1000:
            raise ValueError(f"{ch} 笔画数组不正确")
        polys = []
        for stroke in strokes:
            coords = stroke.get("coordinates") if isinstance(stroke, dict) else None
            if not isinstance(coords, list) or not coords or len(coords) > 10000:
                raise ValueError(f"{ch} 坐标数组不正确")
            points = []
            for p in coords:
                if (
                    not isinstance(p, list)
                    or len(p) != 2
                    or any(
                        type(v) not in (int, float)
                        or not math.isfinite(v)
                        or abs(v) > 1e9
                        for v in p
                    )
                ):
                    raise ValueError(f"{ch} 坐标必须为有限二维数值")
                if not points or tuple(p) != points[-1]:
                    points.append(tuple(p))
            # 点笔画保留为零长度路径，不擅自改成连线或删除。
            polys.append(points if len(points) > 1 else points * 2)
        if ch in seen:
            duplicates.append(
                {"character": ch, "source_index": index, "policy": "保留首次出现的版本"}
            )
            continue
        seen.add(ch)
        xs, ys = zip(*(p for poly in polys for p in poly))
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        extent = max(max(xs) - min(xs), max(ys) - min(ys))
        scale = 0.9 / extent if extent else 1
        normalized = [
            [
                (round((x - cx) * scale * 10000), round((y - cy) * scale * 10000))
                for x, y in poly
            ]
            for poly in polys
        ]
        rows.append(
            {
                "char": ch,
                "lengths": [len(p) for p in normalized],
                "x": [x for p in normalized for x, y in p],
                "y": [y for p in normalized for x, y in p],
                "preserve_origin": True,
            }
        )
    report = dict(
        source=SOURCE,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        license_sha256=hashlib.sha256(license_file.read_bytes()).hexdigest(),
        records=len(entries),
        characters=len(rows),
        duplicates=duplicates,
        stroke_count=sum(len(r["lengths"]) for r in rows),
        transform="逐字等比缩入 0.9 em，居中；保留 y 向下、笔画顺序和方向；仅去除连续重复点",
        experimental=True,
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
        shutil.copyfile(license_file, pending / "LICENSE")
        (pending / "characters.txt").write_text("".join(row["char"] for row in rows), encoding="utf-8")
        (pending / "provenance.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (pending / "README.md").write_text(
            f"# Stroke2Font 行楷 · 实验字库\n\n来源：{SOURCE}，上游 MIT 许可见 LICENSE。\n\n{len(rows)} 个唯一字符，覆盖很小；不是完整行楷字库。保留上游分笔坐标，不新增连笔。缺字将由其他数据集补充，可能混合字体风格。\n",
            encoding="utf-8",
        )
        pending.rename(output)
    except Exception:
        shutil.rmtree(pending)
        raise
    return report
