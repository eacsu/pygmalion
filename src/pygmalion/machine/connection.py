"""系统串口名称的规范化；不打开设备。"""

import re

from . import grbl


def normalize_port(port: str):
    port = port.strip()
    if port.casefold() == "auto":
        return "auto"
    if re.fullmatch(r"COM[1-9][0-9]*", port, re.IGNORECASE):
        return port.upper()
    if re.fullmatch(
        r"/dev/(?:tty[\w.-]+|cu\.[\w.-]+|rfcomm[0-9]+|serial/(?:by-id|by-path)/[^/\s]+)",
        port,
    ) or any(item["device"] == port for item in grbl.serial_ports()):
        return port
    raise ValueError("请选择系统串口，或输入 COM8、/dev/ttyUSB0 等串口名称")
