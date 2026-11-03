"""按冻结的生成器 G-code 粗估时长；不等同于设备实时运动进度。"""

import math
import re

_WORD = re.compile(r"([A-Z])([-+]?(?:\d+(?:\.\d*)?|\.\d+))")


def estimate_seconds(program, machine, start_position=(0.0, 0.0)) -> float | None:
    """包含 XY、Z 和 G4；G0 使用配置空走速度，未计固件限速和加减速。

    实际起始 Z 未在定位接口返回，以配置落笔高度作估算基准。
    只接受本应用生成的毫米绝对坐标指令，未知指令返回不可估算。
    """
    if not program:
        return None
    position = [*start_position, float(machine.get("z_on", 2))]
    feed = float(machine["feed_rate"])
    rapid = float(machine["jog_speed"])
    z_speed = float(machine["z_speed"])
    seconds = 0.0
    for line in program:
        line = line.split(";", 1)[0].strip().upper()
        if not line:
            continue
        words = dict(_WORD.findall(line))
        if line in ("G21", "G90", "M2"):
            continue
        command = words.get("G")
        if command == "4":
            seconds += float(words.get("P", 0))
            continue
        if command not in ("0", "1"):
            return None
        feed = float(words.get("F", feed))
        target = [float(words.get(axis, old)) for axis, old in zip("XYZ", position)]
        rate = (z_speed if "Z" in words else rapid) if command == "0" else feed
        if not math.isfinite(rate) or rate <= 0:
            return None
        seconds += math.dist(position, target) / rate * 60
        position = target
    return round(seconds, 2) if math.isfinite(seconds) and seconds >= 0 else None
