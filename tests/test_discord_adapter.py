"""Tests for DiscordConversationAdapter using discord_msg mock HttpTransport."""

from __future__ import annotations

import json
import unittest
from typing import Any

from discord_msg import DiscordClient, HttpResponse

from agent_desk import (
    ChannelNotAllowedError,
    DeskService,
    DiscordConversationAdapter,
    SQLiteStore,
)


class _MockTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        timeout: float,
        body: bytes | None = None,
    ) -> HttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "timeout": timeout,
                "body": json.loads(body.decode("utf-8")) if body else None,
            }
        )
        if not self._responses:
            raise AssertionError(f"Unexpected HTTP call: {method} {url}")
        return self._responses.pop(0)


def _json_response(payload: Any, status: int = 200) -> HttpResponse:
    return HttpResponse(
        status=status,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
    )


class TestDiscordConversationAdapter(unittest.TestCase):
    def test_allowlist_blocks_unregistered_channel_and_thread(self) -> None:
        transport = _MockTransport([])
        client = DiscordClient("fake-token", transport=transport)
        adapter = DiscordConversationAdapter(
            client=client,
            allowed_channels=["111111111111111111"],
            enforce_allowlist=True,
        )

        with self.assertRaises(ChannelNotAllowedError):
            adapter.post_message("999999999999999999", "blocked")
        with self.assertRaises(ChannelNotAllowedError):
            adapter.send_to_thread("888888888888888888", "blocked")
        self.assertEqual(len(transport.calls), 0)

    def test_end_to_end_ask_and_read_via_discord_msg_client(self) -> None:
        ch_id = "123456789012345678"
        src_msg_id = "1308000000000000001"
        thread_id = "1309500000000000001"
        ask_msg_id = "1309500000000000010"
        reply_msg_id = "1309500000000000020"

        transport = _MockTransport(
            [
                # 1. inbox pull -> GET /channels/{ch_id}/messages
                _json_response(
                    [
                        {
                            "id": src_msg_id,
                            "channel_id": ch_id,
                            "content": "新しいスクリプトを作ってほしい",
                            "timestamp": "2026-11-25T00:00:00+00:00",
                            "author": {
                                "id": "222333444555666777",
                                "username": "owner",
                                "global_name": "Owner",
                                "bot": False,
                            },
                        }
                    ]
                ),
                # 2. create_thread -> POST /channels/{ch_id}/messages/{src_msg_id}/threads
                _json_response(
                    {
                        "id": thread_id,
                        "parent_id": ch_id,
                        "name": "REQ-0001: 新しいスクリプトを作ってほしい",
                        "type": 11,
                        "thread_metadata": {"auto_archive_duration": 1440, "archived": False},
                    }
                ),
                # 3. send_to_thread -> POST /channels/{thread_id}/messages
                _json_response(
                    {
                        "id": ask_msg_id,
                        "channel_id": thread_id,
                        "timestamp": "2026-11-25T00:01:00+00:00",
                    }
                ),
                # 4. read_replies -> GET /channels/{thread_id}/messages?after={ask_msg_id}
                _json_response(
                    [
                        {
                            "id": reply_msg_id,
                            "channel_id": thread_id,
                            "content": "Python でお願いします",
                            "timestamp": "2026-11-25T00:02:00+00:00",
                            "author": {
                                "id": "222333444555666777",
                                "username": "owner",
                                "global_name": "Owner",
                                "bot": False,
                            },
                        }
                    ]
                ),
            ]
        )

        client = DiscordClient("fake-token", transport=transport)
        adapter = DiscordConversationAdapter(client=client, enforce_allowlist=True)

        with SQLiteStore(":memory:") as store:
            svc = DeskService(store, adapter)
            svc.add_desk("dev", ch_id, name="開発部")
            svc.add_actor("dev-mgr", "manager", display_name="開発マネージャー", desk_id="dev")

            pulled = svc.pull_inbox("dev")
            self.assertEqual(len(pulled.created_requests), 1)
            req_id = pulled.created_requests[0].req_id

            asked = svc.ask(req_id, "@everyone 言語は何にしますか？", actor_id="dev-mgr")
            self.assertEqual(asked.request.thread_id, thread_id)
            self.assertEqual(asked.request.thread_cursor, ask_msg_id)
            # Verify mentions are disabled by default in Discord payload
            send_call = transport.calls[2]
            self.assertEqual(send_call["body"]["allowed_mentions"], {"parse": []})
            self.assertIn("[開発マネージャー]", send_call["body"]["content"])

            replies = svc.read_replies(req_id)
            self.assertEqual(len(replies.messages), 1)
            self.assertEqual(replies.messages[0].content, "Python でお願いします")
            self.assertEqual(replies.cursor, reply_msg_id)


if __name__ == "__main__":
    unittest.main()
