"""SQLite persistence store for Agent Desk."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ConflictError, InvalidArgumentsError, NotFoundError, StorageError
from .models import (
    CLOSED_REQUEST_STATUSES,
    VALID_ACTOR_ROLES,
    VALID_REQUEST_STATUSES,
    Actor,
    ActorRole,
    Desk,
    EventType,
    Request,
    RequestEvent,
    RequestStatus,
)

DEFAULT_DB_ENV = "AGENT_DESK_DB"
_UNSET: Any = object()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_db_path() -> Path:
    env_path = os.environ.get(DEFAULT_DB_ENV, "").strip()
    if env_path:
        return Path(env_path)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "agent-desk" / "agent_desk.db"
    return Path.home() / ".config" / "agent-desk" / "agent_desk.db"


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS desks (
    desk_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    adapter_type TEXT NOT NULL DEFAULT 'discord',
    channel_id TEXT NOT NULL,
    inbox_cursor TEXT,
    default_assignee_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actors (
    actor_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    desk_id TEXT,
    external_user_id TEXT,
    is_bot INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (desk_id) REFERENCES desks(desk_id)
);

CREATE TABLE IF NOT EXISTS requests (
    req_id TEXT PRIMARY KEY,
    parent_req_id TEXT,
    desk_id TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL,
    requester_actor_id TEXT,
    requester_external_id TEXT,
    assignee_actor_id TEXT,
    channel_id TEXT NOT NULL,
    source_message_id TEXT,
    thread_id TEXT,
    thread_cursor TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    FOREIGN KEY (parent_req_id) REFERENCES requests(req_id),
    FOREIGN KEY (desk_id) REFERENCES desks(desk_id),
    FOREIGN KEY (requester_actor_id) REFERENCES actors(actor_id),
    FOREIGN KEY (assignee_actor_id) REFERENCES actors(actor_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_channel_source
    ON requests(channel_id, source_message_id)
    WHERE source_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_requests_desk_status
    ON requests(desk_id, status);

CREATE INDEX IF NOT EXISTS idx_requests_parent
    ON requests(parent_req_id);

CREATE TABLE IF NOT EXISTS request_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    req_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_id TEXT,
    external_user_id TEXT,
    external_message_id TEXT,
    content TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (req_id) REFERENCES requests(req_id)
);

CREATE INDEX IF NOT EXISTS idx_events_req_id
    ON request_events(req_id, event_id);
"""


def _row_to_desk(row: sqlite3.Row) -> Desk:
    return Desk(
        desk_id=row["desk_id"],
        name=row["name"],
        adapter_type=row["adapter_type"],
        channel_id=row["channel_id"],
        inbox_cursor=row["inbox_cursor"],
        default_assignee_id=row["default_assignee_id"],
        created_at=row["created_at"],
    )


def _row_to_actor(row: sqlite3.Row) -> Actor:
    return Actor(
        actor_id=row["actor_id"],
        display_name=row["display_name"],
        role=row["role"],
        desk_id=row["desk_id"],
        external_user_id=row["external_user_id"],
        is_bot=bool(row["is_bot"]),
        created_at=row["created_at"],
    )


def _row_to_request(row: sqlite3.Row) -> Request:
    return Request(
        req_id=row["req_id"],
        parent_req_id=row["parent_req_id"],
        desk_id=row["desk_id"],
        title=row["title"],
        body=row["body"],
        status=row["status"],
        requester_actor_id=row["requester_actor_id"],
        requester_external_id=row["requester_external_id"],
        assignee_actor_id=row["assignee_actor_id"],
        channel_id=row["channel_id"],
        source_message_id=row["source_message_id"],
        thread_id=row["thread_id"],
        thread_cursor=row["thread_cursor"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        closed_at=row["closed_at"],
    )


def _row_to_event(row: sqlite3.Row) -> RequestEvent:
    try:
        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
    except json.JSONDecodeError:
        meta = {}
    return RequestEvent(
        event_id=int(row["event_id"]),
        req_id=row["req_id"],
        event_type=row["event_type"],
        actor_id=row["actor_id"],
        external_user_id=row["external_user_id"],
        external_message_id=row["external_message_id"],
        content=row["content"],
        metadata=meta if isinstance(meta, dict) else {},
        created_at=row["created_at"],
    )


class SQLiteStore:
    """SQLite-backed state store for desks, actors, requests, cursors, and events."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            resolved = default_db_path()
            self._db_target = str(resolved)
            resolved.parent.mkdir(parents=True, exist_ok=True)
        elif str(db_path) == ":memory:":
            self._db_target = ":memory:"
        else:
            resolved = Path(db_path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            self._db_target = str(resolved)

        try:
            self._conn = sqlite3.connect(self._db_target)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON;")
            if self._db_target != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.executescript(_SCHEMA_SQL)
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to initialize database '{self._db_target}': {exc}") from exc

    @property
    def db_path(self) -> str:
        return self._db_target

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    # --- Desks ---

    def create_desk(
        self,
        desk_id: str,
        channel_id: str,
        *,
        name: str | None = None,
        adapter_type: str = "discord",
        default_assignee_id: str | None = None,
    ) -> Desk:
        cleaned_id = desk_id.strip()
        cleaned_ch = channel_id.strip()
        if not cleaned_id:
            raise InvalidArgumentsError("desk_id must not be empty.")
        if not cleaned_ch:
            raise InvalidArgumentsError("channel_id must not be empty.")

        now = _utc_now_iso()
        display_name = (name or cleaned_id).strip() or cleaned_id
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO desks (desk_id, name, adapter_type, channel_id, default_assignee_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (cleaned_id, display_name, adapter_type.strip() or "discord", cleaned_ch, default_assignee_id, now),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"Desk '{cleaned_id}' already exists.") from exc
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to create desk '{cleaned_id}': {exc}") from exc
        return self.get_desk(cleaned_id)

    def get_desk(self, desk_id: str) -> Desk:
        row = self._conn.execute(
            "SELECT * FROM desks WHERE desk_id = ?", (desk_id.strip(),)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Desk '{desk_id}' was not found.")
        return _row_to_desk(row)

    def list_desks(self) -> list[Desk]:
        rows = self._conn.execute("SELECT * FROM desks ORDER BY created_at ASC, desk_id ASC").fetchall()
        return [_row_to_desk(r) for r in rows]

    def update_desk_inbox_cursor(self, desk_id: str, cursor: str | None) -> Desk:
        self.get_desk(desk_id)
        try:
            with self._conn:
                self._conn.execute(
                    "UPDATE desks SET inbox_cursor = ? WHERE desk_id = ?",
                    (cursor, desk_id.strip()),
                )
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to update inbox cursor for desk '{desk_id}': {exc}") from exc
        return self.get_desk(desk_id)

    # --- Actors ---

    def create_actor(
        self,
        actor_id: str,
        role: ActorRole,
        *,
        display_name: str | None = None,
        desk_id: str | None = None,
        external_user_id: str | None = None,
        is_bot: bool | None = None,
    ) -> Actor:
        cleaned_id = actor_id.strip()
        if not cleaned_id:
            raise InvalidArgumentsError("actor_id must not be empty.")
        if role not in VALID_ACTOR_ROLES:
            raise InvalidArgumentsError(
                f"Invalid actor role '{role}'. Expected one of: {', '.join(VALID_ACTOR_ROLES)}."
            )
        if desk_id is not None:
            self.get_desk(desk_id)

        resolved_bot = (role != "human") if is_bot is None else bool(is_bot)
        now = _utc_now_iso()
        label = (display_name or cleaned_id).strip() or cleaned_id
        ext_id = external_user_id.strip() if external_user_id else None
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO actors (actor_id, display_name, role, desk_id, external_user_id, is_bot, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cleaned_id, label, role, desk_id, ext_id, int(resolved_bot), now),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"Actor '{cleaned_id}' already exists.") from exc
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to create actor '{cleaned_id}': {exc}") from exc
        return self.get_actor(cleaned_id)

    def get_actor(self, actor_id: str) -> Actor:
        row = self._conn.execute(
            "SELECT * FROM actors WHERE actor_id = ?", (actor_id.strip(),)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Actor '{actor_id}' was not found.")
        return _row_to_actor(row)

    def find_actor_by_external_id(self, external_user_id: str) -> Actor | None:
        cleaned = external_user_id.strip()
        if not cleaned:
            return None
        row = self._conn.execute(
            "SELECT * FROM actors WHERE external_user_id = ? LIMIT 1", (cleaned,)
        ).fetchone()
        return _row_to_actor(row) if row is not None else None

    def list_actors(
        self,
        *,
        desk_id: str | None = None,
        role: str | None = None,
    ) -> list[Actor]:
        clauses: list[str] = []
        params: list[Any] = []
        if desk_id is not None:
            clauses.append("desk_id = ?")
            params.append(desk_id.strip())
        if role is not None:
            clauses.append("role = ?")
            params.append(role.strip())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM actors {where} ORDER BY created_at ASC, actor_id ASC",
            params,
        ).fetchall()
        return [_row_to_actor(r) for r in rows]

    # --- Requests ---

    def next_req_id(self) -> str:
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO counters (name, value) VALUES ('req_seq', 1)
                    ON CONFLICT(name) DO UPDATE SET value = value + 1
                    """
                )
                row = self._conn.execute(
                    "SELECT value FROM counters WHERE name = 'req_seq'"
                ).fetchone()
                seq = int(row["value"]) if row is not None else 1
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to allocate next REQ-ID: {exc}") from exc
        return f"REQ-{seq:04d}"

    def create_request(
        self,
        *,
        desk_id: str,
        title: str,
        body: str,
        channel_id: str,
        req_id: str | None = None,
        parent_req_id: str | None = None,
        status: RequestStatus = "OPEN",
        requester_actor_id: str | None = None,
        requester_external_id: str | None = None,
        assignee_actor_id: str | None = None,
        source_message_id: str | None = None,
        thread_id: str | None = None,
        thread_cursor: str | None = None,
    ) -> Request:
        if status not in VALID_REQUEST_STATUSES:
            raise InvalidArgumentsError(f"Invalid request status '{status}'.")
        if parent_req_id is not None:
            self.get_request(parent_req_id)
        if requester_actor_id is not None:
            self.get_actor(requester_actor_id)
        if assignee_actor_id is not None:
            self.get_actor(assignee_actor_id)

        allocated_id = req_id.strip() if req_id else self.next_req_id()
        now = _utc_now_iso()
        closed_at = now if status in CLOSED_REQUEST_STATUSES else None
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO requests (
                        req_id, parent_req_id, desk_id, title, body, status,
                        requester_actor_id, requester_external_id, assignee_actor_id,
                        channel_id, source_message_id, thread_id, thread_cursor,
                        created_at, updated_at, closed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        allocated_id,
                        parent_req_id,
                        desk_id,
                        title,
                        body,
                        status,
                        requester_actor_id,
                        requester_external_id,
                        assignee_actor_id,
                        channel_id,
                        source_message_id,
                        thread_id,
                        thread_cursor,
                        now,
                        now,
                        closed_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"Request '{allocated_id}' conflicts with an existing record: {exc}") from exc
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to create request '{allocated_id}': {exc}") from exc
        return self.get_request(allocated_id)

    def get_request(self, req_id: str) -> Request:
        row = self._conn.execute(
            "SELECT * FROM requests WHERE req_id = ?", (req_id.strip(),)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Request '{req_id}' was not found.")
        return _row_to_request(row)

    def find_request_by_source_message(
        self,
        channel_id: str,
        source_message_id: str,
    ) -> Request | None:
        row = self._conn.execute(
            "SELECT * FROM requests WHERE channel_id = ? AND source_message_id = ? LIMIT 1",
            (channel_id.strip(), source_message_id.strip()),
        ).fetchone()
        return _row_to_request(row) if row is not None else None

    def list_requests(
        self,
        *,
        desk_id: str | None = None,
        status: str | None = None,
        parent_req_id: str | None = None,
        assignee_actor_id: str | None = None,
        limit: int = 50,
    ) -> list[Request]:
        clauses: list[str] = []
        params: list[Any] = []
        if desk_id is not None:
            clauses.append("desk_id = ?")
            params.append(desk_id.strip())
        if status is not None:
            clauses.append("status = ?")
            params.append(status.strip().upper())
        if parent_req_id is not None:
            clauses.append("parent_req_id = ?")
            params.append(parent_req_id.strip())
        if assignee_actor_id is not None:
            clauses.append("assignee_actor_id = ?")
            params.append(assignee_actor_id.strip())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        rows = self._conn.execute(
            f"SELECT * FROM requests {where} ORDER BY created_at DESC, req_id DESC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_request(r) for r in rows]

    def update_request(
        self,
        req_id: str,
        *,
        status: Any = _UNSET,
        assignee_actor_id: Any = _UNSET,
        source_message_id: Any = _UNSET,
        thread_id: Any = _UNSET,
        thread_cursor: Any = _UNSET,
    ) -> Request:
        existing = self.get_request(req_id)
        updates: list[str] = []
        params: list[Any] = []
        now = _utc_now_iso()

        if status is not _UNSET:
            if status not in VALID_REQUEST_STATUSES:
                raise InvalidArgumentsError(f"Invalid request status '{status}'.")
            updates.append("status = ?")
            params.append(status)
            if status in CLOSED_REQUEST_STATUSES:
                updates.append("closed_at = ?")
                params.append(existing.closed_at or now)
            else:
                updates.append("closed_at = NULL")

        if assignee_actor_id is not _UNSET:
            if assignee_actor_id is not None:
                self.get_actor(assignee_actor_id)
            updates.append("assignee_actor_id = ?")
            params.append(assignee_actor_id)

        if source_message_id is not _UNSET:
            updates.append("source_message_id = ?")
            params.append(source_message_id)

        if thread_id is not _UNSET:
            updates.append("thread_id = ?")
            params.append(thread_id)

        if thread_cursor is not _UNSET:
            updates.append("thread_cursor = ?")
            params.append(thread_cursor)

        if not updates:
            return existing

        updates.append("updated_at = ?")
        params.append(now)
        params.append(existing.req_id)

        try:
            with self._conn:
                self._conn.execute(
                    f"UPDATE requests SET {', '.join(updates)} WHERE req_id = ?",
                    params,
                )
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to update request '{req_id}': {exc}") from exc
        return self.get_request(existing.req_id)

    # --- Events ---

    def add_event(
        self,
        req_id: str,
        event_type: EventType,
        *,
        content: str = "",
        actor_id: str | None = None,
        external_user_id: str | None = None,
        external_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RequestEvent:
        now = _utc_now_iso()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        try:
            with self._conn:
                cur = self._conn.execute(
                    """
                    INSERT INTO request_events (
                        req_id, event_type, actor_id, external_user_id,
                        external_message_id, content, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        req_id,
                        event_type,
                        actor_id,
                        external_user_id,
                        external_message_id,
                        content,
                        meta_json,
                        now,
                    ),
                )
                event_id = int(cur.lastrowid or 0)
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to log event for request '{req_id}': {exc}") from exc
        row = self._conn.execute(
            "SELECT * FROM request_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        assert row is not None
        return _row_to_event(row)

    def list_events(self, req_id: str, *, limit: int = 50) -> list[RequestEvent]:
        self.get_request(req_id)
        rows = self._conn.execute(
            """
            SELECT * FROM request_events
            WHERE req_id = ?
            ORDER BY event_id ASC
            LIMIT ?
            """,
            (req_id.strip(), max(1, int(limit))),
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    # --- Allowlist helpers ---

    def list_allowed_channels(self) -> list[str]:
        rows = self._conn.execute("SELECT DISTINCT channel_id FROM desks").fetchall()
        return [str(r["channel_id"]) for r in rows if r["channel_id"]]

    def list_allowed_threads(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT thread_id FROM requests WHERE thread_id IS NOT NULL"
        ).fetchall()
        return [str(r["thread_id"]) for r in rows if r["thread_id"]]
