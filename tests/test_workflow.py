"""End-to-end workflow tests for Agent Office using InMemoryConversationAdapter."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_office import (
    AgentOfficeService,
    InMemoryConversationAdapter,
    SQLiteStore,
)


class TestAgentOfficeWorkflow(unittest.TestCase):
    def test_inbox_pull_is_idempotent_and_tracks_cursor(self) -> None:
        adapter = InMemoryConversationAdapter()
        adapter.inject_message("ch-dev", "ログイン画面のバグを直してほしい", author_id="u-owner", author_name="Owner")
        adapter.inject_message("ch-dev", "Bot からの通知", author_id="u-bot", author_name="Bot", author_bot=True)

        with SQLiteStore(":memory:") as store:
            svc = AgentOfficeService(store, adapter)
            svc.add_desk("dev", "ch-dev", name="開発部")
            svc.add_actor("owner", "human", display_name="オーナー", external_user_id="u-owner")

            first = svc.pull_inbox("dev")
            self.assertEqual(len(first.created_requests), 1)
            self.assertEqual(first.created_requests[0].req_id, "REQ-0001")
            self.assertEqual(first.created_requests[0].requester_actor_id, "owner")
            self.assertEqual(first.created_requests[0].requester_external_id, "u-owner")
            self.assertIsNotNone(first.cursor)

            # Second pull with no new messages must not duplicate
            second = svc.pull_inbox("dev")
            self.assertEqual(len(second.created_requests), 0)
            self.assertEqual(second.cursor, first.cursor)

            # New message after cursor is picked up as REQ-0002
            adapter.inject_message("ch-dev", "CSV エクスポート機能を追加したい", author_id="u-owner", author_name="Owner")
            third = svc.pull_inbox("dev")
            self.assertEqual(len(third.created_requests), 1)
            self.assertEqual(third.created_requests[0].req_id, "REQ-0002")

    def test_ask_wait_resume_after_restart_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "desk.db"
            adapter = InMemoryConversationAdapter()
            adapter.inject_message("ch-dev", "ダッシュボードを作ってほしい", author_id="u-owner", author_name="Owner")

            # Process 1: pull -> ask -> receive first answer
            with SQLiteStore(db_path) as store1:
                svc1 = AgentOfficeService(store1, adapter)
                svc1.add_desk("dev", "ch-dev", name="開発部")
                svc1.add_actor("owner", "human", display_name="オーナー", external_user_id="u-owner")
                svc1.add_actor("dev-mgr", "manager", display_name="開発マネージャー", desk_id="dev")

                pulled = svc1.pull_inbox("dev")
                req_id = pulled.created_requests[0].req_id

                ask_res = svc1.ask(req_id, "対象ユーザーは社内向けですか？", actor_id="dev-mgr")
                self.assertTrue(ask_res.thread_created)
                self.assertEqual(ask_res.request.status, "CLARIFYING")
                thread_id = ask_res.request.thread_id
                assert thread_id is not None

                # Another user's message should be ignored when waiting for requester
                adapter.inject_message(thread_id, "横から失礼します", author_id="u-other", author_name="Other")
                adapter.inject_message(thread_id, "はい、社内向けです。", author_id="u-owner", author_name="Owner")

                waited1 = svc1.wait_for_answer(req_id, timeout=5.0, poll_interval=0.5)
                self.assertFalse(waited1.timed_out)
                self.assertEqual(len(waited1.messages), 1)
                self.assertEqual(waited1.messages[0].content, "はい、社内向けです。")

            # Process 2 (simulated restart): reopen SQLite DB and continue from persisted cursor
            with SQLiteStore(db_path) as store2:
                svc2 = AgentOfficeService(store2, adapter)
                # No new messages yet -> timeout returns timed_out=True without losing cursor
                timed_out = svc2.wait_for_answer(req_id, timeout=0.0, poll_interval=0.1)
                self.assertTrue(timed_out.timed_out)
                self.assertEqual(len(timed_out.messages), 0)

                # Requester sends follow-up
                adapter.inject_message(thread_id, "納期は来週金曜でお願いします。", author_id="u-owner", author_name="Owner")
                resumed = svc2.read_replies(req_id)
                self.assertEqual(len(resumed.messages), 1)
                self.assertEqual(resumed.messages[0].content, "納期は来週金曜でお願いします。")

                # Manager posts completion report and closes request
                rep = svc2.reply(req_id, "完了しました！", actor_id="dev-mgr", status="DONE")
                self.assertEqual(rep.request.status, "DONE")
                self.assertIsNotNone(rep.request.closed_at)

                req, events = svc2.get_request_detail(req_id)
                event_types = [e.event_type for e in events]
                self.assertEqual(
                    event_types,
                    ["CREATED", "THREAD_CREATED", "ASK", "ANSWER", "ANSWER", "REPLY"],
                )
                self.assertEqual(req.status, "DONE")

    def test_parent_child_delegation_and_human_waiting_status(self) -> None:
        adapter = InMemoryConversationAdapter()
        with SQLiteStore(":memory:") as store:
            svc = AgentOfficeService(store, adapter)
            svc.add_desk("dev", "ch-dev", name="開発部")
            svc.add_actor("owner", "human", display_name="オーナー", external_user_id="u-owner")
            svc.add_actor("dev-mgr", "manager", display_name="開発マネージャー", desk_id="dev")
            svc.add_actor("dev-w1", "worker", display_name="実装担当1", desk_id="dev")

            parent = svc.create_request(
                "dev",
                "新機能リリースの準備",
                "設計と実装をお願いします",
                requester_actor_id="owner",
                assignee_actor_id="dev-mgr",
                post_to_channel=True,
            )
            child = svc.create_request(
                "dev",
                "API エンドポイント実装",
                "親タスクの実装パート",
                parent_req_id=parent.req_id,
                requester_actor_id="dev-mgr",
                assignee_actor_id="dev-w1",
            )
            self.assertEqual(child.parent_req_id, parent.req_id)

            children = svc.list_requests(parent_req_id=parent.req_id)
            self.assertEqual([c.req_id for c in children], [child.req_id])

            updated, _ = svc.set_status(parent.req_id, "WAITING_HUMAN", actor_id="dev-mgr", note="設計承認待ち")
            self.assertEqual(updated.status, "WAITING_HUMAN")


if __name__ == "__main__":
    unittest.main()
