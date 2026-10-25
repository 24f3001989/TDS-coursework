import json
import sqlite3
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).with_name("ga3-q2.db")


def get_connection():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()

    conn.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            principal TEXT NOT NULL,
            context_id TEXT NOT NULL,
            state TEXT NOT NULL,
            task_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_principal
        ON tasks(principal);

        CREATE TABLE IF NOT EXISTS messages (
            principal TEXT NOT NULL,
            message_id TEXT NOT NULL,
            message_hash TEXT NOT NULL,
            task_id TEXT NOT NULL,
            PRIMARY KEY(principal, message_id)
        );

        CREATE TABLE IF NOT EXISTS package_cache (
            package_hash TEXT PRIMARY KEY,
            decision_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    conn.close()


def save_task(task: dict, principal: str):
    conn = get_connection()

    conn.execute("BEGIN IMMEDIATE")

    conn.execute(
        """
        INSERT INTO tasks
        (id, principal, context_id, state, task_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            task["id"],
            principal,
            task["contextId"],
            task["status"]["state"],
            json.dumps(task, separators=(",", ":"), ensure_ascii=False),
        ),
    )

    conn.commit()
    conn.close()


def update_task(task: dict, principal: str):
    conn = get_connection()

    conn.execute("BEGIN IMMEDIATE")

    cursor = conn.execute(
        """
        UPDATE tasks
        SET state = ?,
            task_json = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
          AND principal = ?
          AND state NOT IN (
              'TASK_STATE_COMPLETED',
              'TASK_STATE_CANCELED'
          )
        """,
        (
            task["status"]["state"],
            json.dumps(task, separators=(",", ":"), ensure_ascii=False),
            task["id"],
            principal,
        ),
    )

    if cursor.rowcount != 1:
        conn.rollback()
        conn.close()
        return False

    conn.commit()
    conn.close()
    return True


def get_task(task_id: str, principal: str) -> Optional[dict]:
    conn = get_connection()

    row = conn.execute(
        """
        SELECT task_json
        FROM tasks
        WHERE id = ?
          AND principal = ?
        """,
        (task_id, principal),
    ).fetchone()

    conn.close()

    if not row:
        return None

    return json.loads(row["task_json"])


def list_tasks_for_principal(principal: str):
    conn = get_connection()

    rows = conn.execute(
        """
        SELECT task_json
        FROM tasks
        WHERE principal = ?
        ORDER BY created_at ASC
        """,
        (principal,),
    ).fetchall()

    conn.close()

    return [
        json.loads(row["task_json"])
        for row in rows
    ]


def get_message(
    principal: str,
    message_id: str,
):
    conn = get_connection()

    row = conn.execute(
        """
        SELECT message_hash, task_id
        FROM messages
        WHERE principal = ?
          AND message_id = ?
        """,
        (principal, message_id),
    ).fetchone()

    conn.close()

    if not row:
        return None

    return {
        "message_hash": row["message_hash"],
        "task_id": row["task_id"],
    }


def save_message(
    principal: str,
    message_id: str,
    message_hash: str,
    task_id: str,
):
    conn = get_connection()

    conn.execute(
        """
        INSERT INTO messages
        (principal, message_id, message_hash, task_id)
        VALUES (?, ?, ?, ?)
        """,
        (
            principal,
            message_id,
            message_hash,
            task_id,
        ),
    )

    conn.commit()
    conn.close()


def get_cached_decision(package_hash: str):
    conn = get_connection()

    row = conn.execute(
        """
        SELECT decision_json
        FROM package_cache
        WHERE package_hash = ?
        """,
        (package_hash,),
    ).fetchone()

    conn.close()

    if not row:
        return None

    return json.loads(row["decision_json"])


def save_cached_decision(
    package_hash: str,
    decision: dict,
):
    conn = get_connection()

    conn.execute(
        """
        INSERT OR IGNORE INTO package_cache
        (package_hash, decision_json)
        VALUES (?, ?)
        """,
        (
            package_hash,
            json.dumps(
                decision,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        ),
    )

    conn.commit()
    conn.close()