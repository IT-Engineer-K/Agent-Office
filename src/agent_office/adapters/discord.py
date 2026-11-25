"""Discord ConversationAdapter backed by discord-message-cli (discord_msg)."""

from __future__ import annotations

import os
from collections.abc import Collection, Mapping
from typing import Any

from discord_msg import (
    DiscordClient,
    DiscordMsgError,
    HttpTransport,
    MessageItem,
)
from discord_msg.auth import DEFAULT_TOKEN_ENV, resolve_token

from ..errors import AdapterError, ChannelNotAllowedError, InvalidArgumentsError
from ..models import (
    CreatedThread,
    IncomingMessage,
    MessageBatch,
    PostedMessage,
    WaitBatch,
)


def _to_incoming(item: MessageItem) -> IncomingMessage:
    return IncomingMessage(
        message_id=item.message_id,
        channel_id=item.channel_id,
        author_id=item.author_id,
        author_name=item.author_display_name or item.author_username or item.author_id,
        author_bot=item.author_bot,
        timestamp=item.timestamp,
        content=item.content,
        referenced_message_id=item.referenced_message_id,
    )


class DiscordConversationAdapter:
    """ConversationAdapter implementation delegating to discord_msg.DiscordClient."""

    adapter_type: str = "discord"

    def __init__(
        self,
        *,
        client: DiscordClient | None = None,
        token: str | None = None,
        transport: HttpTransport | None = None,
        env: Mapping[str, str] | None = None,
        allowed_channels: Collection[str] | None = None,
        allowed_threads: Collection[str] | None = None,
        enforce_allowlist: bool = True,
    ) -> None:
        self._client: DiscordClient | None = client
        self._token = token
        self._transport = transport
        self._env = env
        self._enforce_allowlist = enforce_allowlist
        self._allowed_channels: set[str] = set(allowed_channels or ())
        self._allowed_threads: set[str] = set(allowed_threads or ())

    def _get_client(self) -> DiscordClient:
        if self._client is not None:
            return self._client
        try:
            if self._token is not None and self._token.strip():
                resolved_token = self._token.strip()
                if resolved_token.lower().startswith("bot "):
                    resolved_token = resolved_token[4:].strip()
            else:
                environ = self._env if self._env is not None else os.environ
                resolved_token = resolve_token(
                    prompt_token=False,
                    token_stdin=False,
                    env_var=DEFAULT_TOKEN_ENV,
                    env=environ,
                    stdin=None,
                )
            self._client = DiscordClient(resolved_token, transport=self._transport)
            return self._client
        except DiscordMsgError as exc:
            raise AdapterError(f"Discord auth/init failed ({exc.code}): {exc.message}") from exc

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
            raise ChannelNotAllowedError(
                f"Channel '{cleaned}' is not in the Agent Office allowlist."
            )
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
            raise ChannelNotAllowedError(
                f"Thread '{cleaned}' is not in the Agent Office allowlist."
            )
        return cleaned

    def post_message(
        self,
        channel_id: str,
        content: str,
        *,
        allow_mentions: bool = False,
    ) -> PostedMessage:
        cid = self._check_channel(channel_id)
        try:
            res = self._get_client().send_message(
                cid,
                content,
                allow_mentions=allow_mentions,
            )
        except DiscordMsgError as exc:
            raise AdapterError(f"Discord post_message failed ({exc.code}): {exc.message}") from exc
        return PostedMessage(
            channel_id=res.channel_id,
            message_id=res.message_id,
            timestamp=res.timestamp,
        )

    def create_thread(
        self,
        channel_id: str,
        message_id: str,
        name: str,
    ) -> CreatedThread:
        cid = self._check_channel(channel_id)
        try:
            res = self._get_client().create_thread(cid, message_id, name)
        except DiscordMsgError as exc:
            raise AdapterError(f"Discord create_thread failed ({exc.code}): {exc.message}") from exc
        self._allowed_threads.add(res.thread_id)
        return CreatedThread(
            thread_id=res.thread_id,
            parent_channel_id=res.parent_channel_id,
            source_message_id=res.source_message_id,
            name=res.name,
        )

    def send_to_thread(
        self,
        thread_id: str,
        content: str,
        *,
        allow_mentions: bool = False,
    ) -> PostedMessage:
        tid = self._check_thread(thread_id)
        try:
            res = self._get_client().send_message(
                thread_id=tid,
                content=content,
                allow_mentions=allow_mentions,
            )
        except DiscordMsgError as exc:
            raise AdapterError(f"Discord send_to_thread failed ({exc.code}): {exc.message}") from exc
        return PostedMessage(
            channel_id=res.channel_id,
            message_id=res.message_id,
            timestamp=res.timestamp,
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

        kwargs: dict[str, Any] = {
            "after": after,
            "limit": limit,
            "author_id": author_id,
            "exclude_bots": exclude_bots,
        }
        if channel_id:
            kwargs["channel_id"] = self._check_channel(channel_id)
        else:
            assert thread_id is not None
            kwargs["thread_id"] = self._check_thread(thread_id)

        try:
            res = self._get_client().list_messages(**kwargs)
        except DiscordMsgError as exc:
            raise AdapterError(f"Discord list_messages failed ({exc.code}): {exc.message}") from exc

        return MessageBatch(
            channel_id=res.channel_id,
            after=res.after,
            cursor=res.cursor,
            messages=tuple(_to_incoming(m) for m in res.messages),
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
        try:
            res = self._get_client().wait_for_messages(
                thread_id=tid,
                after=after,
                timeout=timeout,
                poll_interval=poll_interval,
                author_id=author_id,
                exclude_bots=exclude_bots,
            )
        except DiscordMsgError as exc:
            raise AdapterError(
                f"Discord wait_for_messages failed ({exc.code}): {exc.message}"
            ) from exc

        return WaitBatch(
            channel_id=res.channel_id,
            after=res.after,
            cursor=res.cursor,
            messages=tuple(_to_incoming(m) for m in res.messages),
            timed_out=res.timed_out,
            polls=res.polls,
        )
