"""Core domain models and adapter DTOs for Agent Desk."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ActorRole = Literal["human", "manager", "worker"]
VALID_ACTOR_ROLES: tuple[str, ...] = ("human", "manager", "worker")

RequestStatus = Literal[
    "OPEN",
    "CLARIFYING",
    "WAITING_HUMAN",
    "IN_PROGRESS",
    "DONE",
    "CANCELLED",
]
VALID_REQUEST_STATUSES: tuple[str, ...] = (
    "OPEN",
    "CLARIFYING",
    "WAITING_HUMAN",
    "IN_PROGRESS",
    "DONE",
    "CANCELLED",
)
CLOSED_REQUEST_STATUSES: frozenset[str] = frozenset({"DONE", "CANCELLED"})

EventType = Literal[
    "CREATED",
    "THREAD_CREATED",
    "ASK",
    "ANSWER",
    "REPLY",
    "STATUS_CHANGED",
    "ASSIGNED",
]


@dataclass(frozen=True)
class Desk:
    desk_id: str
    name: str
    adapter_type: str
    channel_id: str
    inbox_cursor: str | None = None
    default_assignee_id: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "desk_id": self.desk_id,
            "name": self.name,
            "adapter_type": self.adapter_type,
            "channel_id": self.channel_id,
            "inbox_cursor": self.inbox_cursor,
            "default_assignee_id": self.default_assignee_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Actor:
    actor_id: str
    display_name: str
    role: ActorRole
    desk_id: str | None = None
    external_user_id: str | None = None
    is_bot: bool = False
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "display_name": self.display_name,
            "role": self.role,
            "desk_id": self.desk_id,
            "external_user_id": self.external_user_id,
            "is_bot": self.is_bot,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Request:
    req_id: str
    desk_id: str
    title: str
    body: str
    status: RequestStatus
    channel_id: str
    parent_req_id: str | None = None
    requester_actor_id: str | None = None
    requester_external_id: str | None = None
    assignee_actor_id: str | None = None
    source_message_id: str | None = None
    thread_id: str | None = None
    thread_cursor: str | None = None
    created_at: str = ""
    updated_at: str = ""
    closed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "req_id": self.req_id,
            "parent_req_id": self.parent_req_id,
            "desk_id": self.desk_id,
            "title": self.title,
            "body": self.body,
            "status": self.status,
            "requester_actor_id": self.requester_actor_id,
            "requester_external_id": self.requester_external_id,
            "assignee_actor_id": self.assignee_actor_id,
            "channel_id": self.channel_id,
            "source_message_id": self.source_message_id,
            "thread_id": self.thread_id,
            "thread_cursor": self.thread_cursor,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "closed_at": self.closed_at,
        }


@dataclass(frozen=True)
class RequestEvent:
    event_id: int
    req_id: str
    event_type: EventType
    content: str = ""
    actor_id: str | None = None
    external_user_id: str | None = None
    external_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "req_id": self.req_id,
            "event_type": self.event_type,
            "actor_id": self.actor_id,
            "external_user_id": self.external_user_id,
            "external_message_id": self.external_message_id,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class PostedMessage:
    channel_id: str
    message_id: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class CreatedThread:
    thread_id: str
    parent_channel_id: str
    source_message_id: str
    name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "parent_channel_id": self.parent_channel_id,
            "source_message_id": self.source_message_id,
            "name": self.name,
        }


@dataclass(frozen=True)
class IncomingMessage:
    message_id: str
    channel_id: str
    author_id: str
    author_name: str
    author_bot: bool
    timestamp: str
    content: str
    referenced_message_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "channel_id": self.channel_id,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "author_bot": self.author_bot,
            "timestamp": self.timestamp,
            "content": self.content,
            "referenced_message_id": self.referenced_message_id,
        }


@dataclass(frozen=True)
class MessageBatch:
    channel_id: str
    after: str | None
    cursor: str | None
    messages: tuple[IncomingMessage, ...]


@dataclass(frozen=True)
class WaitBatch:
    channel_id: str
    after: str | None
    cursor: str | None
    messages: tuple[IncomingMessage, ...]
    timed_out: bool
    polls: int


@dataclass(frozen=True)
class InboxPullResult:
    desk_id: str
    channel_id: str
    previous_cursor: str | None
    cursor: str | None
    created_requests: tuple[Request, ...]
    skipped_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "desk_id": self.desk_id,
            "channel_id": self.channel_id,
            "previous_cursor": self.previous_cursor,
            "cursor": self.cursor,
            "created_count": len(self.created_requests),
            "skipped_count": self.skipped_count,
            "requests": [r.to_dict() for r in self.created_requests],
        }


@dataclass(frozen=True)
class AskResult:
    request: Request
    thread_created: bool
    posted: PostedMessage
    event: RequestEvent

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "req_id": self.request.req_id,
            "status": self.request.status,
            "thread_id": self.request.thread_id,
            "thread_created": self.thread_created,
            "thread_cursor": self.request.thread_cursor,
            "posted": self.posted.to_dict(),
            "event": self.event.to_dict(),
        }


@dataclass(frozen=True)
class RepliesResult:
    request: Request
    previous_cursor: str | None
    cursor: str | None
    messages: tuple[IncomingMessage, ...]
    events: tuple[RequestEvent, ...]
    timed_out: bool = False
    polls: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "req_id": self.request.req_id,
            "thread_id": self.request.thread_id,
            "previous_cursor": self.previous_cursor,
            "cursor": self.cursor,
            "timed_out": self.timed_out,
            "polls": self.polls,
            "count": len(self.messages),
            "messages": [m.to_dict() for m in self.messages],
        }


@dataclass(frozen=True)
class ReplyResult:
    request: Request
    posted: PostedMessage
    event: RequestEvent

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "req_id": self.request.req_id,
            "status": self.request.status,
            "thread_id": self.request.thread_id,
            "thread_cursor": self.request.thread_cursor,
            "posted": self.posted.to_dict(),
            "event": self.event.to_dict(),
        }
