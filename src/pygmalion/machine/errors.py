"""设备操作错误，与网络协议无关。"""


class MachineError(Exception):
    def __init__(self, kind: str, payload: dict):
        self.kind = kind
        self.payload = payload
        super().__init__(payload.get("error", kind))


class ExecutionCancelled(Exception):
    """已确认停止发送并完成收尾。"""


class ExecutionRejected(Exception):
    """运动开始前已确定拒绝执行。"""
