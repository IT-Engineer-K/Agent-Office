"""In-memory ConversationAdapter for deterministic offline testing."""

from __future__ import annotations

from collections.abc import Callable, Collection
from datetime import datetime, timezone

from ..errors import ChannelNotAllowedError, InvalidArgumentsError
from ..models import (
    CreatedThread,
    IncomingMessage,
    MessageBatch,
    PostedMessage,
    WaitBatch,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryConversationAdapter:
    """In-memory ConversationAdapter implementing channels, threads, and cursor filtering."""

    adapter_type: str = "memory"

    def __init__(
        self,
        *,
        bot_author_id: str = "bot-agent-office",
        bot_author_name: str = "AgentOfficeBot",
        allowed_channels: Collection[str] | None = None,
        allowed_threads: Collection[str] | None = None,
        enforce_allowlist: bool = False,
        on_wait_poll: Callable[[int, str, str | None], None] | None = None,
    ) -> None:
        self._bot_author_id = bot_author_id
        self._bot_author_name = bot_author_name
        self._enforce_allowlist = enforce_allowlist
        self._allowed_channels: set[str] = set(allowed_channels or ())
        self._allowed_threads: set[str] = set(allowed_threads or ())
        self._on_wait_poll = on_wait_poll
        self._next_id = 1000
        self._messages: dict[str, list[IncomingMessage]] = {}
        self._threads: dict[str, CreatedThread] = {}

    def _alloc_id(self) -> str:
        self._next_id += 1
        return str(self._next_id)

    def allow_channel(self, channel_id: str) -> None:
        cleaned = channel_id.strip()
        if cleaned:
            self._allowed_channels.add(cleaned)

    def allow_thread(self, thread_id: str) -> None:
        cleaned = thread_id.strip()
        if cleaned:
            self._allowed_threads.add(cleaned)

    def _check_channel(self, channel_id: str) -> str:
        cleaned = channel_id.strip()
        if not cleaned:
            raise InvalidArgumentsError("channel_id must not be empty.")
        if self._enforce_allowlist and cleaned not in self._allowed_channels:
            raise ChannelNotAllowedError(f"Channel '{cleaned}' is not allowed.")
        return cleaned

    def _check_thread(self, thread_id: str) -> str:
        cleaned = thread_id.strip()
        if not cleaned:
            raise InvalidArgumentsError("thread_id must not be empty.")
        if (
            self._enforce_allowlist
            and cleaned not in self._allowed_threads
            and cleaned not in self._allowed_channels
        ):
            raise ChannelNotAllowedError(f"Thread '{cleaned}' is not allowed.")
        return cleaned

    def inject_message(
        self,
        target_id: str,
        content: str,
        *,
        author_id: str = "user-human-1",
        author_name: str = "Owner",
        author_bot: bool = False,
        referenced_message_id: str | None = None,
    ) -> IncomingMessage:
        """Test helper to simulate an external human or agent posting a message."""
        msg = IncomingMessage(
            message_id=self._alloc_id(),
            channel_id=target_id,
            author_id=author_id,
            author_name=author_name,
            author_bot=author_bot,
            timestamp=_utc_now_iso(),
            content=content,
            referenced_message_id=referenced_message_id,
        )
        self._messages.setdefault(target_id, []).append(msg)
        return msg

    def post_message(
        self,
        channel_id: str,
        content: str,
        *,
        allow_mentions: bool = False,
    ) -> PostedMessage:
        _ = allow_mentions
        cid = self._check_channel(channel_id)
        msg = self.inject_message(
            cid,
            content,
            author_id=self._bot_author_id,
            author_name=self._bot_author_name,
            author_bot=True,
        )
        return PostedMessage(
            channel_id=cid,
            message_id=msg.message_id,
            timestamp=msg.timestamp,
        )

    def create_thread(
        self,
        channel_id: str,
        message_id: str,
        name: str,
    ) -> CreatedThread:
        cid = self._check_channel(channel_id)
        tid = f"9{self._alloc_id()}"
        thread = CreatedThread(
            thread_id=tid,
            parent_channel_id=cid,
            source_message_id=message_id,
            name=name,
        )
        self._threads[tid] = thread
        self._messages.setdefault(tid, [])
        self._allowed_threads.add(tid)
        return thread

    def send_to_thread(
        self,
        thread_id: str,
        content: str,
        *,
        allow_mentions: bool = False,
    ) -> PostedMessage:
        _ = allow_mentions
        tid = self._check_thread(thread_id)
        msg = self.inject_message(
            tid,
            content,
            author_id=self._bot_author_id,
            author_name=self._bot_author_name,
            author_bot=True,
        )
        return PostedMessage(
            channel_id=tid,
            message_id=msg.message_id,
            timestamp=msg.timestamp,
        )

    def list_messages(
        self,
        *,
        channel_id: str | None = None,
        thread_id: str | None = None,
        after: str | None = None,
        limit: int = 50,
        author_id: str | None = None,
        exclude_bots: bool = False,
    ) -> MessageBatch:
        if channel_id and thread_id:
            raise InvalidArgumentsError("Specify either channel_id or thread_id, not both.")
        if not channel_id and not thread_id:
            raise InvalidArgumentsError("Either channel_id or thread_id is required.")

        target_id = self._check_channel(channel_id) if channel_id else self._check_thread(thread_id or "")
        all_msgs = list(self._messages.get(target_id, []))

        after_int = int(after) if after and after.isdigit() else None
        if after_int is not None:
            scanned = [m for m in all_msgs if int(m.message_id) > after_int]
        else:
            scanned = all_msgs

        cursor = after
        if scanned:
            cursor = scanned[-1].message_id

        filtered: list[IncomingMessage] = []
        for m in scanned:
            if exclude_bots and m.author_bot:
                continue
            if author_id is not None and m.author_id != author_id:
                continue
            filtered.append(m)
            if len(filtered) >= limit:
                break

        return MessageBatch(
            channel_id=target_id,
            after=after,
            cursor=cursor,
            messages=tuple(filtered),
        )

    def wait_for_messages(
        self,
        *,
        thread_id: str,
        after: str | None = None,
        timeout: float = 60.0,
        poll_interval: float = 2.0,
        author_id: str | None = None,
        exclude_bots: bool = False,
    ) -> WaitBatch:
        tid = self._check_thread(thread_id)
        max_polls = max(1, int(timeout // max(poll_interval, 0.01)) + 1) if timeout > 0 else 1
        max_polls = min(max_polls, 5)
        cursor = after
        for poll in range(1, max_polls + 1):
            if self._on_wait_poll is not None:
                self._on_wait_poll(poll, tid, cursor)
            batch = self.list_messages(
                thread_id=tid,
                after=cursor,
                author_id=author_id,
                exclude_bots=exclude_bots,
            )
            cursor = batch.cursor or cursor
            if batch.messages:
                return WaitBatch(
                    channel_id=tid,
                    after=after,
                    cursor=cursor,
                    messages=batch.messages,
                    timed_out=False,
                    polls=poll,
                )
        return WaitBatch(
            channel_id=tid,
            after=after,
            cursor=cursor,
            messages=(),
            timed_out=True,
            polls=max_polls,
        )
