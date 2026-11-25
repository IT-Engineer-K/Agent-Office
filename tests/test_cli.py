"""CLI tests for Agent Office verifying JSON/table output and exit codes."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from agent_office import ExitCode, InMemoryConversationAdapter
from agent_office.cli import run_cli


class TestAgentOfficeCLI(unittest.TestCase):
    def _exec(
        self,
        argv: list[str],
        *,
        adapter: InMemoryConversationAdapter,
        stdin_text: str = "",
    ) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        code = run_cli(
            argv,
            adapter=adapter,
            stdout=out,
            stderr=err,
            stdin=io.StringIO(stdin_text),
        )
        return code, out.getvalue(), err.getvalue()

    def test_cli_full_json_flow(self) -> None:
        adapter = InMemoryConversationAdapter()
        adapter.inject_message("ch-ops", "サーバーの監視設定を確認してほしい", author_id="u-owner", author_name="Owner")

        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "agent_office.db")

            # 1. Register desk & actors
            code, out, err = self._exec(
                ["desk", "add", "ops", "--channel", "ch-ops", "--name", "運用部", "--db", db, "--format", "json"],
                adapter=adapter,
            )
            self.assertEqual(code, int(ExitCode.OK), err)
            self.assertEqual(json.loads(out)["desk"]["desk_id"], "ops")

            code, out, err = self._exec(
                ["actor", "add", "ops-mgr", "--role", "manager", "--desk", "ops", "--db", db, "--format", "json"],
                adapter=adapter,
            )
            self.assertEqual(code, int(ExitCode.OK), err)

            # 2. Pull inbox
            code, out, err = self._exec(
                ["inbox", "pull", "--desk", "ops", "--db", db, "--format", "json"],
                adapter=adapter,
            )
            self.assertEqual(code, int(ExitCode.OK), err)
            pull_data = json.loads(out)
            self.assertEqual(pull_data["created_count"], 1)
            req_id = pull_data["requests"][0]["req_id"]

            # 3. Ask question via --stdin
            code, out, err = self._exec(
                ["req", "ask", req_id, "--stdin", "--actor", "ops-mgr", "--db", db, "--format", "json"],
                adapter=adapter,
                stdin_text="対象サーバー名を教えてください。",
            )
            self.assertEqual(code, int(ExitCode.OK), err)
            ask_data = json.loads(out)
            self.assertTrue(ask_data["thread_created"])
            thread_id = ask_data["thread_id"]

            # 4. Simulate owner reply and wait
            adapter.inject_message(thread_id, "prod-web-01 です。", author_id="u-owner", author_name="Owner")
            code, out, err = self._exec(
                ["req", "wait", req_id, "--timeout", "5", "--poll-interval", "0.2", "--db", db, "--format", "json"],
                adapter=adapter,
            )
            self.assertEqual(code, int(ExitCode.OK), err)
            wait_data = json.loads(out)
            self.assertFalse(wait_data["timed_out"])
            self.assertEqual(wait_data["messages"][0]["content"], "prod-web-01 です。")

            # 5. Reply and close
            code, out, err = self._exec(
                ["req", "reply", req_id, "確認完了しました。", "--actor", "ops-mgr", "--status", "DONE", "--db", db, "--format", "json"],
                adapter=adapter,
            )
            self.assertEqual(code, int(ExitCode.OK), err)
            self.assertEqual(json.loads(out)["status"], "DONE")

            # 6. Show detail in table format
            code, out, err = self._exec(
                ["req", "show", req_id, "--db", db],
                adapter=adapter,
            )
            self.assertEqual(code, int(ExitCode.OK), err)
            self.assertIn(req_id, out)
            self.assertIn("DONE", out)

    def test_cli_returns_not_found_for_missing_request(self) -> None:
        adapter = InMemoryConversationAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "agent_office.db")
            code, out, err = self._exec(
                ["req", "show", "REQ-9999", "--db", db],
                adapter=adapter,
            )
            self.assertEqual(code, int(ExitCode.NOT_FOUND))
            self.assertEqual(out, "")
            self.assertIn("NOT_FOUND", err)


if __name__ == "__main__":
    unittest.main()
