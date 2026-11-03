"""维护操作的设备适配，路径及串口细节留在设备边界内。"""

import logging
import uuid

logger = logging.getLogger(__name__)
from datetime import UTC, datetime
from pathlib import Path

from .. import config
from . import grbl


class Maintenance:
    def __init__(self, controller):
        self.controller = controller

    def ports(self):
        return grbl.serial_ports()

    def probe(self):
        with self.controller.operation():
            return self._probe()

    def _probe(self):
        return [
            {
                k: v
                for k, v in item.items()
                if k
                in (
                    "device",
                    "description",
                    "hwid",
                    "vid",
                    "pid",
                    "reachable",
                    "grbl",
                    "firmware",
                    "error",
                )
            }
            for item in grbl.probe_grbl_ports(int(config.CONFIG["machine"]["baud"]))
        ]

    def backup_info(self, path):
        path = Path(path)
        return {
            "id": path.stem,
            "created_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
            "download_url": f"/api/v1/machine/backups/{path.stem}/download",
        }

    def backups(self):
        return [
            self.backup_info(path)
            for path in sorted(
                grbl.BACKUP_DIR.glob("grbl-settings-*.txt"), reverse=True
            )
            if path.name != "grbl-settings-latest.txt"
        ]

    def download(self, identifier):
        if Path(identifier).name != identifier or not identifier.startswith(
            "grbl-settings-"
        ):
            raise FileNotFoundError()
        return (grbl.BACKUP_DIR / (identifier + ".txt")).read_bytes()

    def preview(self, changes):
        return grbl.settings_commands(changes)

    def apply(self, changes, session):
        controller = self.controller
        with (
            controller.operation(session=session, reuse=True),
            controller.device_connection(config.CONFIG["machine"], reuse=True) as link,
        ):
            backup = link.backup(reason="公开接口控制板参数写入前备份")
            config.save_section("device_context", {"revision": uuid.uuid4().hex})
            result = {
                "kind": "firmware",
                "backup": self.backup_info(backup),
                "applied": [],
                "failed": [],
                "unknown": [],
                "not_applied": [],
            }
            keys = list(changes)
            for index, key in enumerate(keys):
                try:
                    link.write_settings({key: changes[key]}, dry_run=False)
                    result["applied"].append(key)
                except grbl.CommandRejected:
                    result["failed"].append(key)
                    result["not_applied"] = keys[index + 1 :]
                    break
                except Exception:
                    logger.exception("控制板参数结果无法确认")
                    # 通信返回无法证明参数是否写入，不能自动重试。
                    result["unknown"].append(key)
                    result["not_applied"] = keys[index + 1 :]
                    break
            return result
