"""Table and JSON output formatters for Agent Desk CLI."""

from __future__ import annotations

import json
from typing import Any

from .models import (
    Actor,
    AskResult,
    Desk,
    InboxPullResult,
    RepliesResult,
    ReplyResult,
    Request,
    RequestEvent,
)


def _dump_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _render_table(headers: tuple[str, ...], rows: list[tuple[str, ...]], empty_msg: str) -> str:
    if not rows:
        return empty_msg
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    lines = [
        sep,
        "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |",
        sep,
    ]
    for row in rows:
        lines.append("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) + " |")
    lines.append(sep)
    return "\n".join(lines)


def format_desks(desks: list[Desk], fmt: str) -> str:
    if fmt == "json":
        return _dump_json({"ok": True, "count": len(desks), "desks": [d.to_dict() for d in desks]})
    rows = [
        (d.desk_id, d.name, d.adapter_type, d.channel_id, d.inbox_cursor or "-")
        for d in desks
    ]
    return _render_table(("Desk ID", "Name", "Adapter", "Channel ID", "Inbox Cursor"), rows, "No desks registered.")


def format_desk(desk: Desk, fmt: str) -> str:
    if fmt == "json":
        return _dump_json({"ok": True, "desk": desk.to_dict()})
    return "\n".join(
        [
            f"Desk ID      : {desk.desk_id}",
            f"Name         : {desk.name}",
            f"Adapter      : {desk.adapter_type}",
            f"Channel ID   : {desk.channel_id}",
            f"Inbox Cursor : {desk.inbox_cursor or '-'}",
        ]
    )


def format_actors(actors: list[Actor], fmt: str) -> str:
    if fmt == "json":
        return _dump_json({"ok": True, "count": len(actors), "actors": [a.to_dict() for a in actors]})
    rows = [
        (a.actor_id, a.display_name, a.role, a.desk_id or "-", a.external_user_id or "-")
        for a in actors
    ]
    return _render_table(("Actor ID", "Name", "Role", "Desk", "External ID"), rows, "No actors registered.")


def format_actor(actor: Actor, fmt: str) -> str:
    if fmt == "json":
        return _dump_json({"ok": True, "actor": actor.to_dict()})
    return "\n".join(
        [
            f"Actor ID     : {actor.actor_id}",
            f"Name         : {actor.display_name}",
            f"Role         : {actor.role}",
            f"Desk         : {actor.desk_id or '-'}",
            f"External ID  : {actor.external_user_id or '-'}",
        ]
    )


def format_inbox_pull(result: InboxPullResult, fmt: str) -> str:
    if fmt == "json":
        return _dump_json(result.to_dict())
    lines = [
        f"Desk ID      : {result.desk_id}",
        f"Channel ID   : {result.channel_id}",
        f"Cursor       : {result.cursor or '-'}",
        f"Created      : {len(result.created_requests)}",
        f"Skipped      : {result.skipped_count}",
    ]
    for req in result.created_requests:
        lines.append(f"  - {req.req_id} [{req.status}] {req.title}")
    return "\n".join(lines)


def format_requests(requests: list[Request], fmt: str) -> str:
    if fmt == "json":
        return _dump_json({"ok": True, "count": len(requests), "requests": [r.to_dict() for r in requests]})
    rows = [
        (
            r.req_id,
            r.desk_id,
            r.status,
            r.parent_req_id or "-",
            r.assignee_actor_id or "-",
            r.title[:40],
        )
        for r in requests
    ]
    return _render_table(
        ("REQ ID", "Desk", "Status", "Parent", "Assignee", "Title"),
        rows,
        "No requests found.",
    )


def format_request(req: Request, fmt: str) -> str:
    if fmt == "json":
        return _dump_json({"ok": True, "request": req.to_dict()})
    return "\n".join(
        [
            f"REQ ID        : {req.req_id}",
            f"Parent REQ    : {req.parent_req_id or '-'}",
            f"Desk          : {req.desk_id}",
            f"Status        : {req.status}",
            f"Title         : {req.title}",
            f"Requester     : {req.requester_actor_id or req.requester_external_id or '-'}",
            f"Assignee      : {req.assignee_actor_id or '-'}",
            f"Channel ID    : {req.channel_id}",
            f"Thread ID     : {req.thread_id or '-'}",
            f"Thread Cursor : {req.thread_cursor or '-'}",
        ]
    )


def format_request_detail(req: Request, events: list[RequestEvent], fmt: str) -> str:
    if fmt == "json":
        return _dump_json(
            {
                "ok": True,
                "request": req.to_dict(),
                "events": [e.to_dict() for e in events],
            }
        )
    lines = [format_request(req, "table"), "", "Body:", req.body, "", f"Events ({len(events)}):"]
    for ev in events:
        who = ev.actor_id or ev.external_user_id or "-"
        snippet = ev.content.replace("\n", " ")[:70]
        lines.append(f"  #{ev.event_id} [{ev.event_type}] ({who}) {snippet}")
    return "\n".join(lines)


def format_ask(result: AskResult, fmt: str) -> str:
    if fmt == "json":
        return _dump_json(result.to_dict())
    return "\n".join(
        [
            f"REQ ID         : {result.request.req_id}",
            f"Status         : {result.request.status}",
            f"Thread ID      : {result.request.thread_id}",
            f"Thread Created : {result.thread_created}",
            f"Message ID     : {result.posted.message_id}",
            f"Thread Cursor  : {result.request.thread_cursor}",
        ]
    )


def format_replies(result: RepliesResult, fmt: str) -> str:
    if fmt == "json":
        return _dump_json(result.to_dict())
    lines = [
        f"REQ ID        : {result.request.req_id}",
        f"Thread ID     : {result.request.thread_id}",
        f"Timed Out     : {result.timed_out}",
        f"Cursor        : {result.cursor or '-'}",
        f"Messages      : {len(result.messages)}",
    ]
    for msg in result.messages:
        lines.append(f"  - [{msg.message_id}] {msg.author_name}: {msg.content}")
    return "\n".join(lines)


def format_reply(result: ReplyResult, fmt: str) -> str:
    if fmt == "json":
        return _dump_json(result.to_dict())
    return "\n".join(
        [
            f"REQ ID        : {result.request.req_id}",
            f"Status        : {result.request.status}",
            f"Thread ID     : {result.request.thread_id}",
            f"Message ID    : {result.posted.message_id}",
            f"Thread Cursor : {result.request.thread_cursor}",
        ]
    )
