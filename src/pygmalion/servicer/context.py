"""组装领域资源并委托其生命周期。"""

from .. import config, storage
from ..machine.controller import DeviceController
from .execution import ExecutionService


class ServiceContext:
    def __init__(self, *, dry_run: bool = False):
        self.machine = DeviceController()
        self.execution = ExecutionService(self.machine, dry_run=dry_run)

    def start(self):
        config.ensure_dirs()
        storage.init_db()
        self.execution.start()

    def stop(self):
        try:
            self.execution.stop()
        finally:
            self.machine.stop()
