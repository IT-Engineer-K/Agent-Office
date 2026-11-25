"""Abstract conversation adapter protocol for Agent Desk."""

from __future__ import annotations

from typing import Protocol

from ..models import CreatedThread, MessageBatch, PostedMessage, WaitBatch


class ConversationAdapter(Protocol):
    """Platform-agnostic messaging interface used by DeskService."""

    adapter_type: str

    def allow_channel(self, channel_id: str) -> None:
        """Register a channel ID in the adapter's allowlist (if enforced)."""
        ...

    def allow_thread(self, thread_id: str) -> None:
        """Register a thread ID in the adapter's allowlist (if enforced)."""
        ...

    def post_message(
        self,
        channel_id: str,
        content: str,
        *,
        allow_mentions: bool = False,
    ) -> PostedMessage:
        """Post a message to a top-level channel."""
        ...

    def create_thread(
        self,
        channel_id: str,
        message_id: str,
        name: str,
    ) -> CreatedThread:
        """Create a thread anchored to an existing channel message."""
        ...

    def send_to_thread(
        self,
        thread_id: str,
        content: str,
        *,
        allow_mentions: bool = False,
    ) -> PostedMessage:
        """Post a message inside an existing thread."""
        ...

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
        """List messages in a channel or thread after an optional cursor."""
        ...

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
        """Wait for new matching messages in a thread until timeout."""
        ...
