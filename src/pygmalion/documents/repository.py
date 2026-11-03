"""SQLite 文档版本更新，避免并发客户端静默覆盖。"""

import json
import uuid

from ..execution.repository import now
from ..storage import connect


class Conflict(Exception):
    pass


class Missing(Exception):
    pass


def initialize():
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS workspace_documents (
            id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
            document TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            create_key TEXT UNIQUE
        )""")


def resource(row):
    return {key: row[key] for key in ("id", "revision", "created_at", "updated_at")} | {
        "document": json.loads(row["document"])
    }


def create(document, key):
    value = json.dumps(document, ensure_ascii=False)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute(
            "SELECT * FROM workspace_documents WHERE create_key=?", (key,)
        ).fetchone()
        if old:
            return resource(old)
        identifier, timestamp = "doc_" + uuid.uuid4().hex, now()
        conn.execute(
            "INSERT INTO workspace_documents VALUES(?,1,?,?,?,?)",
            (identifier, value, timestamp, timestamp, key),
        )
        return resource(
            conn.execute(
                "SELECT * FROM workspace_documents WHERE id=?", (identifier,)
            ).fetchone()
        )


def get(identifier):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM workspace_documents WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise Missing(identifier)
        return resource(row)


def update(identifier, document, revision):
    with connect() as conn:
        result = conn.execute(
            "UPDATE workspace_documents SET revision=revision+1,document=?,updated_at=? WHERE id=? AND revision=?",
            (json.dumps(document, ensure_ascii=False), now(), identifier, revision),
        )
        if not result.rowcount:
            if (
                conn.execute(
                    "SELECT 1 FROM workspace_documents WHERE id=?", (identifier,)
                ).fetchone()
                is None
            ):
                raise Missing(identifier)
            raise Conflict(identifier)
        return resource(
            conn.execute(
                "SELECT * FROM workspace_documents WHERE id=?", (identifier,)
            ).fetchone()
        )


def list_documents(limit=100):
    with connect() as conn:
        rows = conn.execute(
            "SELECT id,revision,created_at,updated_at,json_extract(document,'$.name') AS name,json_array_length(document,'$.elements') AS element_count FROM workspace_documents ORDER BY updated_at DESC,id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
