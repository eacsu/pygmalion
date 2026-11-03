"""持久化执行资源和提交去重；SQL 约束不泄露到应用服务。"""

import json
from datetime import UTC, datetime

from ..storage import connect

TERMINAL = ("succeeded", "failed", "cancelled", "interrupted")


def now():
    return datetime.now(UTC).isoformat()


class Conflict(Exception):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_plans(id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS execution_jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, data TEXT NOT NULL, snapshot TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS execution_operations(id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS execution_keys(scope TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL, resource TEXT NOT NULL, PRIMARY KEY(scope,key));
CREATE TABLE IF NOT EXISTS execution_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS firmware_previews(id TEXT PRIMARY KEY, data TEXT NOT NULL);
"""


def initialize():
    with connect() as conn:
        conn.executescript(SCHEMA)
        if not conn.execute(
            "SELECT 1 FROM execution_metadata WHERE key='history_imported'"
        ).fetchone():
            for row in conn.execute("SELECT * FROM print_jobs ORDER BY id"):
                old = dict(row)
                meta = json.loads(old.get("snapshot") or "{}")
                status = {"done": "succeeded", "queued": "cancelled"}.get(
                    old["status"], "interrupted"
                )
                if not old.get("started_at") and old["status"] in (
                    "failed",
                    "cancelled",
                ):
                    status = old["status"]
                data = {
                    "id": old["id"],
                    "plan_id": None,
                    "mode": "simulate" if old.get("dry_run") else "execute",
                    "status": status,
                    "created_at": old["created_at"],
                    "started_at": old.get("started_at"),
                    "finished_at": old.get("finished_at"),
                    "sent": old.get("sent", 0),
                    "total": old.get("total", 0),
                    "title": meta.get("title", ""),
                    "message": old.get("error", ""),
                    "percent": 0,
                }
                conn.execute(
                    "INSERT OR IGNORE INTO execution_jobs VALUES(?,?,?,?)",
                    (old["id"], status, json.dumps(data), json.dumps({"legacy": old})),
                )
            conn.execute(
                "INSERT INTO execution_metadata VALUES('history_imported','1')"
            )
        for table in ("execution_jobs", "execution_operations"):
            for row in conn.execute(
                f"SELECT id,data FROM {table} WHERE status IN ('queued','running','cancelling')"
            ):
                data = json.loads(row["data"])
                data["status"] = (
                    "cancelled" if data["status"] == "queued" else "interrupted"
                )
                data["error"] = {
                    "code": "service_restarted",
                    "message": "服务重启，任务不会自动重发",
                    "details": {},
                    "retry_advice": "query_status",
                }
                if table == "execution_jobs":
                    data["finished_at"] = now()
                else:
                    data["updated_at"] = now()
                conn.execute(
                    f"UPDATE {table} SET status=?,data=? WHERE id=?",
                    (data["status"], json.dumps(data), row["id"]),
                )


def put_plan(identifier, data):
    with connect() as conn:
        conn.execute(
            "INSERT INTO execution_plans VALUES(?,?)",
            (identifier, json.dumps(data, ensure_ascii=False)),
        )


def get_plan(identifier):
    with connect() as conn:
        row = conn.execute(
            "SELECT data FROM execution_plans WHERE id=?", (identifier,)
        ).fetchone()
        return json.loads(row["data"]) if row else None


def find_key(scope, key, fingerprint):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM execution_keys WHERE scope=? AND key=?", (scope, key)
        ).fetchone()
        if row and row["fingerprint"] != fingerprint:
            raise Conflict()
        return row["resource"] if row else None


def create_resource(kind, data, payload, key, fingerprint):
    table = "execution_jobs" if kind == "jobs" else "execution_operations"
    column = "snapshot" if kind == "jobs" else "payload"
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM execution_keys WHERE scope=? AND key=?", (kind, key)
        ).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                raise Conflict()
            return row["resource"], False
        if kind == "jobs":
            cursor = conn.execute(
                f"INSERT INTO {table}(status,data,{column}) VALUES(?,?,?)",
                (data["status"], "{}", json.dumps(payload)),
            )
            data["id"] = cursor.lastrowid
            conn.execute(
                f"UPDATE {table} SET data=? WHERE id=?", (json.dumps(data), data["id"])
            )
        else:
            conn.execute(
                f"INSERT INTO {table} VALUES(?,?,?,?)",
                (data["id"], data["status"], json.dumps(data), json.dumps(payload)),
            )
        conn.execute(
            "INSERT INTO execution_keys VALUES(?,?,?,?)",
            (kind, key, fingerprint, str(data["id"])),
        )
        return str(data["id"]), True


def get_resource(kind, identifier):
    table = "execution_jobs" if kind == "jobs" else "execution_operations"
    with connect() as conn:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE id=?", (identifier,)
        ).fetchone()
        return dict(row) if row else None


def update_resource(kind, data):
    table = "execution_jobs" if kind == "jobs" else "execution_operations"
    with connect() as conn:
        conn.execute(
            f"UPDATE {table} SET status=?,data=? WHERE id=?",
            (data["status"], json.dumps(data), data["id"]),
        )


def list_jobs(before=None, status=None, limit=50):
    clauses, params = [], []
    if before is not None:
        clauses.append("id < ?")
        params.append(before)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connect() as conn:
        rows = conn.execute(
            "SELECT data FROM execution_jobs" + where + " ORDER BY id DESC LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
    items = [json.loads(row["data"]) for row in rows]
    return items[:limit], items[limit - 1]["id"] if len(items) > limit else None


def save_preview(data):
    with connect() as conn:
        conn.execute(
            "INSERT INTO firmware_previews VALUES(?,?)", (data["id"], json.dumps(data))
        )


def get_preview(identifier):
    with connect() as conn:
        row = conn.execute(
            "SELECT data FROM firmware_previews WHERE id=?", (identifier,)
        ).fetchone()
        return json.loads(row["data"]) if row else None


def list_operations(limit=50):
    with connect() as conn:
        return [
            json.loads(row["data"])
            for row in conn.execute(
                "SELECT data FROM execution_operations ORDER BY rowid DESC LIMIT ?",
                (limit,),
            )
        ]


def remember_session(key, identifier):
    with connect() as conn:
        conn.execute(
            "INSERT INTO execution_keys VALUES(?,?,?,?)",
            ("sessions", key, "session", identifier),
        )


def next_queued_job():
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM execution_jobs WHERE status='queued' ORDER BY id LIMIT 1"
        ).fetchone()
        return int(row["id"]) if row else None


def queue_snapshot():
    with connect() as conn:
        active = conn.execute(
            "SELECT data FROM execution_jobs WHERE status IN ('running','cancelling') ORDER BY id LIMIT 1"
        ).fetchone()
        queued = conn.execute(
            "SELECT data FROM execution_jobs WHERE status='queued' ORDER BY id LIMIT 200"
        ).fetchall()
        count = conn.execute(
            "SELECT count(*) FROM execution_jobs WHERE status='queued'"
        ).fetchone()[0]
        return {
            "running": json.loads(active["data"]) if active else None,
            "queued": [json.loads(row["data"]) for row in queued],
            "queued_total": count,
        }


def bind_job_snapshot(identifier, snapshot):
    with connect() as conn:
        conn.execute(
            "UPDATE execution_jobs SET snapshot=? WHERE id=?",
            (json.dumps(snapshot, ensure_ascii=False), identifier),
        )
