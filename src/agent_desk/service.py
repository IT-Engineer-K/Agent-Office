"""Workflow service coordinating desks, actors, requests, and conversation adapters."""

from __future__ import annotations

from .adapters.base import ConversationAdapter
from .errors import InvalidArgumentsError
from .models import (
    VALID_REQUEST_STATUSES,
    Actor,
    ActorRole,
    AskResult,
    Desk,
    InboxPullResult,
    RepliesResult,
    ReplyResult,
    Request,
    RequestEvent,
    RequestStatus,
)
from .store import SQLiteStore


def _derive_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:80]
    return fallback[:80]


def _default_thread_name(req: Request) -> str:
    raw = f"{req.req_id}: {req.title}".strip()
    return raw[:90]


class DeskService:
    """High-level Agent Desk operations built on SQLiteStore + ConversationAdapter."""

    def __init__(self, store: SQLiteStore, adapter: ConversationAdapter) -> None:
        self.store = store
        self.adapter = adapter
        self._sync_allowlists()

    def _sync_allowlists(self) -> None:
        for channel_id in self.store.list_allowed_channels():
            self.adapter.allow_channel(channel_id)
        for thread_id in self.store.list_allowed_threads():
            self.adapter.allow_thread(thread_id)

    def _format_outbound(self, text: str, actor_id: str | None) -> str:
        body = text.strip()
        if not body:
            raise InvalidArgumentsError("Message content must not be empty.")
        if not actor_id:
            return body
        actor = self.store.get_actor(actor_id)
        return f"[{actor.display_name}] {body}"

    def _ensure_thread(
        self,
        req: Request,
        *,
        thread_name: str | None = None,
        allow_mentions: bool = False,
    ) -> tuple[Request, bool]:
        if req.thread_id:
            self.adapter.allow_thread(req.thread_id)
            return req, False

        self.adapter.allow_channel(req.channel_id)
        source_msg_id = req.source_message_id
        if not source_msg_id:
            anchor_text = f"[{req.req_id}] {req.title}"
            if req.body and req.body != req.title:
                anchor_text = f"{anchor_text}\n{req.body}"
            posted_anchor = self.adapter.post_message(
                req.channel_id,
                anchor_text[:1900],
                allow_mentions=allow_mentions,
            )
            source_msg_id = posted_anchor.message_id
            req = self.store.update_request(req.req_id, source_message_id=source_msg_id)

        created = self.adapter.create_thread(
            req.channel_id,
            source_msg_id,
            (thread_name or _default_thread_name(req))[:100],
        )
        req = self.store.update_request(req.req_id, thread_id=created.thread_id)
        self.store.add_event(
            req.req_id,
            "THREAD_CREATED",
            content=created.name,
            metadata={"thread_id": created.thread_id, "source_message_id": source_msg_id},
        )
        return req, True

    def _resolve_reply_filter(
        self,
        req: Request,
        *,
        any_user: bool,
        author_id: str | None,
    ) -> tuple[str | None, bool]:
        if author_id is not None and author_id.strip():
            return author_id.strip(), False
        if any_user:
            return None, False
        if req.requester_external_id:
            return req.requester_external_id, False
        return None, True

    # --- Desk & Actor management ---

    def add_desk(
        self,
        desk_id: str,
        channel_id: str,
        *,
        name: str | None = None,
        adapter_type: str | None = None,
        default_assignee_id: str | None = None,
    ) -> Desk:
        desk = self.store.create_desk(
            desk_id,
            channel_id,
            name=name,
            adapter_type=adapter_type or self.adapter.adapter_type,
            default_assignee_id=default_assignee_id,
        )
        self.adapter.allow_channel(desk.channel_id)
        return desk

    def list_desks(self) -> list[Desk]:
        return self.store.list_desks()

    def add_actor(
        self,
        actor_id: str,
        role: ActorRole,
        *,
        display_name: str | None = None,
        desk_id: str | None = None,
        external_user_id: str | None = None,
        is_bot: bool | None = None,
    ) -> Actor:
        return self.store.create_actor(
            actor_id,
            role,
            display_name=display_name,
            desk_id=desk_id,
            external_user_id=external_user_id,
            is_bot=is_bot,
        )

    def list_actors(
        self,
        *,
        desk_id: str | None = None,
        role: str | None = None,
    ) -> list[Actor]:
        return self.store.list_actors(desk_id=desk_id, role=role)

    # --- Inbox intake & Request creation ---

    def pull_inbox(
        self,
        desk_id: str,
        *,
        prefix: str | None = None,
        limit: int = 50,
        exclude_bots: bool = True,
    ) -> InboxPullResult:
        desk = self.store.get_desk(desk_id)
        self.adapter.allow_channel(desk.channel_id)
        previous_cursor = desk.inbox_cursor

        batch = self.adapter.list_messages(
            channel_id=desk.channel_id,
            after=previous_cursor,
            limit=limit,
            exclude_bots=exclude_bots,
        )

        created: list[Request] = []
        skipped = 0
        for msg in batch.messages:
            if prefix is not None and not msg.content.startswith(prefix):
                skipped += 1
                continue
            existing = self.store.find_request_by_source_message(desk.channel_id, msg.message_id)
            if existing is not None:
                skipped += 1
                continue

            actor = self.store.find_actor_by_external_id(msg.author_id)
            title = _derive_title(msg.content, fallback=f"Request from {msg.author_name}")
            req = self.store.create_request(
                desk_id=desk.desk_id,
                title=title,
                body=msg.content,
                channel_id=desk.channel_id,
                requester_actor_id=actor.actor_id if actor else None,
                requester_external_id=msg.author_id,
                assignee_actor_id=desk.default_assignee_id,
                source_message_id=msg.message_id,
            )
            self.store.add_event(
                req.req_id,
                "CREATED",
                actor_id=actor.actor_id if actor else None,
                external_user_id=msg.author_id,
                external_message_id=msg.message_id,
                content=msg.content,
                metadata={"source": "inbox_pull"},
            )
            created.append(req)

        new_cursor = batch.cursor or previous_cursor
        if new_cursor != previous_cursor:
            self.store.update_desk_inbox_cursor(desk.desk_id, new_cursor)

        return InboxPullResult(
            desk_id=desk.desk_id,
            channel_id=desk.channel_id,
            previous_cursor=previous_cursor,
            cursor=new_cursor,
            created_requests=tuple(created),
            skipped_count=skipped,
        )

    def create_request(
        self,
        desk_id: str,
        title: str,
        body: str = "",
        *,
        parent_req_id: str | None = None,
        requester_actor_id: str | None = None,
        requester_external_id: str | None = None,
        assignee_actor_id: str | None = None,
        post_to_channel: bool = False,
        allow_mentions: bool = False,
    ) -> Request:
        desk = self.store.get_desk(desk_id)
        cleaned_title = title.strip()
        if not cleaned_title:
            raise InvalidArgumentsError("Request title must not be empty.")
        cleaned_body = body.strip() or cleaned_title

        resolved_ext_id = requester_external_id
        if resolved_ext_id is None and requester_actor_id is not None:
            requester = self.store.get_actor(requester_actor_id)
            resolved_ext_id = requester.external_user_id

        resolved_assignee = assignee_actor_id or desk.default_assignee_id
        req_id = self.store.next_req_id()
        source_msg_id: str | None = None

        if post_to_channel:
            self.adapter.allow_channel(desk.channel_id)
            header = f"[{req_id}] {cleaned_title}"
            if parent_req_id:
                header = f"[{req_id} <- {parent_req_id}] {cleaned_title}"
            payload = f"{header}\n{cleaned_body}" if cleaned_body != cleaned_title else header
            posted = self.adapter.post_message(
                desk.channel_id,
                payload[:1900],
                allow_mentions=allow_mentions,
            )
            source_msg_id = posted.message_id

        req = self.store.create_request(
            req_id=req_id,
            desk_id=desk.desk_id,
            title=cleaned_title,
            body=cleaned_body,
            channel_id=desk.channel_id,
            parent_req_id=parent_req_id,
            requester_actor_id=requester_actor_id,
            requester_external_id=resolved_ext_id,
            assignee_actor_id=resolved_assignee,
            source_message_id=source_msg_id,
        )
        self.store.add_event(
            req.req_id,
            "CREATED",
            actor_id=requester_actor_id,
            external_user_id=resolved_ext_id,
            external_message_id=source_msg_id,
            content=cleaned_body,
            metadata={"source": "manual", "parent_req_id": parent_req_id},
        )
        return req

    def list_requests(
        self,
        *,
        desk_id: str | None = None,
        status: str | None = None,
        parent_req_id: str | None = None,
        assignee_actor_id: str | None = None,
        limit: int = 50,
    ) -> list[Request]:
        return self.store.list_requests(
            desk_id=desk_id,
            status=status,
            parent_req_id=parent_req_id,
            assignee_actor_id=assignee_actor_id,
            limit=limit,
        )

    def get_request_detail(
        self,
        req_id: str,
        *,
        event_limit: int = 50,
    ) -> tuple[Request, list[RequestEvent]]:
        req = self.store.get_request(req_id)
        events = self.store.list_events(req.req_id, limit=event_limit)
        return req, events

    # --- Thread conversation workflow ---

    def ask(
        self,
        req_id: str,
        question: str,
        *,
        actor_id: str | None = None,
        thread_name: str | None = None,
        allow_mentions: bool = False,
    ) -> AskResult:
        req = self.store.get_request(req_id)
        formatted = self._format_outbound(question, actor_id)
        req, thread_created = self._ensure_thread(
            req,
            thread_name=thread_name,
            allow_mentions=allow_mentions,
        )
        assert req.thread_id is not None

        posted = self.adapter.send_to_thread(
            req.thread_id,
            formatted,
            allow_mentions=allow_mentions,
        )
        req = self.store.update_request(
            req.req_id,
            status="CLARIFYING",
            thread_cursor=posted.message_id,
        )
        event = self.store.add_event(
            req.req_id,
            "ASK",
            actor_id=actor_id,
            external_message_id=posted.message_id,
            content=question.strip(),
            metadata={"thread_id": req.thread_id},
        )
        return AskResult(
            request=req,
            thread_created=thread_created,
            posted=posted,
            event=event,
        )

    def read_replies(
        self,
        req_id: str,
        *,
        any_user: bool = False,
        author_id: str | None = None,
        limit: int = 50,
    ) -> RepliesResult:
        req = self.store.get_request(req_id)
        if not req.thread_id:
            raise InvalidArgumentsError(
                f"Request '{req.req_id}' does not have a thread yet. Run 'req ask' or 'req reply' first."
            )
        self.adapter.allow_thread(req.thread_id)
        previous_cursor = req.thread_cursor
        target_author, exclude_bots = self._resolve_reply_filter(
            req,
            any_user=any_user,
            author_id=author_id,
        )

        batch = self.adapter.list_messages(
            thread_id=req.thread_id,
            after=previous_cursor,
            limit=limit,
            author_id=target_author,
            exclude_bots=exclude_bots,
        )

        events: list[RequestEvent] = []
        for msg in batch.messages:
            actor = self.store.find_actor_by_external_id(msg.author_id)
            ev = self.store.add_event(
                req.req_id,
                "ANSWER",
                actor_id=actor.actor_id if actor else None,
                external_user_id=msg.author_id,
                external_message_id=msg.message_id,
                content=msg.content,
                metadata={"author_name": msg.author_name},
            )
            events.append(ev)

        new_cursor = batch.cursor or previous_cursor
        if new_cursor != previous_cursor:
            req = self.store.update_request(req.req_id, thread_cursor=new_cursor)

        return RepliesResult(
            request=req,
            previous_cursor=previous_cursor,
            cursor=new_cursor,
            messages=batch.messages,
            events=tuple(events),
            timed_out=False,
            polls=1,
        )

    def wait_for_answer(
        self,
        req_id: str,
        *,
        timeout: float = 60.0,
        poll_interval: float = 2.0,
        any_user: bool = False,
        author_id: str | None = None,
    ) -> RepliesResult:
        req = self.store.get_request(req_id)
        if not req.thread_id:
            raise InvalidArgumentsError(
                f"Request '{req.req_id}' does not have a thread yet. Run 'req ask' or 'req reply' first."
            )
        self.adapter.allow_thread(req.thread_id)
        previous_cursor = req.thread_cursor
        target_author, exclude_bots = self._resolve_reply_filter(
            req,
            any_user=any_user,
            author_id=author_id,
        )

        batch = self.adapter.wait_for_messages(
            thread_id=req.thread_id,
            after=previous_cursor,
            timeout=timeout,
            poll_interval=poll_interval,
            author_id=target_author,
            exclude_bots=exclude_bots,
        )

        events: list[RequestEvent] = []
        for msg in batch.messages:
            actor = self.store.find_actor_by_external_id(msg.author_id)
            ev = self.store.add_event(
                req.req_id,
                "ANSWER",
                actor_id=actor.actor_id if actor else None,
                external_user_id=msg.author_id,
                external_message_id=msg.message_id,
                content=msg.content,
                metadata={"author_name": msg.author_name},
            )
            events.append(ev)

        new_cursor = batch.cursor or previous_cursor
        if new_cursor != previous_cursor:
            req = self.store.update_request(req.req_id, thread_cursor=new_cursor)

        return RepliesResult(
            request=req,
            previous_cursor=previous_cursor,
            cursor=new_cursor,
            messages=batch.messages,
            events=tuple(events),
            timed_out=batch.timed_out,
            polls=batch.polls,
        )

    def reply(
        self,
        req_id: str,
        message: str,
        *,
        actor_id: str | None = None,
        status: RequestStatus | None = None,
        allow_mentions: bool = False,
    ) -> ReplyResult:
        if status is not None and status not in VALID_REQUEST_STATUSES:
            raise InvalidArgumentsError(f"Invalid request status '{status}'.")

        req = self.store.get_request(req_id)
        formatted = self._format_outbound(message, actor_id)
        req, _ = self._ensure_thread(req, allow_mentions=allow_mentions)
        assert req.thread_id is not None

        posted = self.adapter.send_to_thread(
            req.thread_id,
            formatted,
            allow_mentions=allow_mentions,
        )
        previous_status = req.status
        if status is not None:
            req = self.store.update_request(
                req.req_id,
                status=status,
                thread_cursor=posted.message_id,
            )
        else:
            req = self.store.update_request(
                req.req_id,
                thread_cursor=posted.message_id,
            )

        event = self.store.add_event(
            req.req_id,
            "REPLY",
            actor_id=actor_id,
            external_message_id=posted.message_id,
            content=message.strip(),
            metadata={"status_before": previous_status, "status_after": req.status},
        )
        return ReplyResult(request=req, posted=posted, event=event)

    def set_status(
        self,
        req_id: str,
        status: RequestStatus,
        *,
        actor_id: str | None = None,
        note: str = "",
    ) -> tuple[Request, RequestEvent]:
        normalized = status.strip().upper()
        if normalized not in VALID_REQUEST_STATUSES:
            raise InvalidArgumentsError(
                f"Invalid status '{status}'. Expected one of: {', '.join(VALID_REQUEST_STATUSES)}."
            )
        before = self.store.get_request(req_id)
        updated = self.store.update_request(before.req_id, status=normalized)
        event = self.store.add_event(
            updated.req_id,
            "STATUS_CHANGED",
            actor_id=actor_id,
            content=note.strip(),
            metadata={"from": before.status, "to": updated.status},
        )
        return updated, event
