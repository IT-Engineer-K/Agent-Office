"""Command-line entry point for Agent Desk."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import TextIO

from . import __version__
from .adapters.base import ConversationAdapter
from .adapters.discord import DiscordConversationAdapter
from .errors import AgentDeskError, ExitCode, InvalidArgumentsError
from .formatter import (
    format_actor,
    format_actors,
    format_ask,
    format_desk,
    format_desks,
    format_inbox_pull,
    format_replies,
    format_reply,
    format_request,
    format_request_detail,
    format_requests,
)
from .models import VALID_ACTOR_ROLES, VALID_REQUEST_STATUSES
from .service import DeskService
from .store import SQLiteStore


class _RaisingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvalidArgumentsError(message)


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        help="Path to SQLite database file (defaults to AGENT_DESK_DB or OS app config path).",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format on stdout: 'table' (default) or 'json'.",
    )


def _read_message_arg(positional: str | None, option: str | None, use_stdin: bool, stdin: TextIO) -> str:
    if use_stdin:
        text = stdin.read().strip()
        if not text:
            raise InvalidArgumentsError("Message content from stdin is empty.")
        return text
    text = (option if option is not None else positional) or ""
    if not text.strip():
        raise InvalidArgumentsError("Message content is required (positional, --message, or --stdin).")
    return text.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = _RaisingArgumentParser(
        prog="agent-desk",
        description="Human-centered request desk and conversation workflow CLI for AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"agent-desk {__version__}")

    top = parser.add_subparsers(dest="group")

    # --- desk ---
    desk_parser = top.add_parser("desk", help="Manage department desks (channels/allowlist).")
    desk_sub = desk_parser.add_subparsers(dest="action")

    desk_add = desk_sub.add_parser("add", help="Register a department desk and allow its channel.")
    desk_add.add_argument("desk_id", help="Short desk identifier (e.g. dev, research).")
    desk_add.add_argument("--channel", required=True, help="Target channel ID.")
    desk_add.add_argument("--name", help="Human-readable desk name.")
    desk_add.add_argument("--default-assignee", help="Default assignee actor_id.")
    _add_output_options(desk_add)

    desk_list = desk_sub.add_parser("list", help="List registered desks.")
    _add_output_options(desk_list)

    # --- actor ---
    actor_parser = top.add_parser("actor", help="Manage humans, manager agents, and worker agents.")
    actor_sub = actor_parser.add_subparsers(dest="action")

    actor_add = actor_sub.add_parser("add", help="Register an actor.")
    actor_add.add_argument("actor_id", help="Unique actor identifier (e.g. owner, dev-manager).")
    actor_add.add_argument("--role", required=True, choices=VALID_ACTOR_ROLES, help="Actor role.")
    actor_add.add_argument("--name", help="Display name.")
    actor_add.add_argument("--desk", help="Affiliated desk_id.")
    actor_add.add_argument("--external-user-id", help="External chat user ID (e.g. Discord author_id).")
    _add_output_options(actor_add)

    actor_list = actor_sub.add_parser("list", help="List registered actors.")
    actor_list.add_argument("--desk", help="Filter by desk_id.")
    actor_list.add_argument("--role", choices=VALID_ACTOR_ROLES, help="Filter by role.")
    _add_output_options(actor_list)

    # --- inbox ---
    inbox_parser = top.add_parser("inbox", help="Pull incoming requests from a desk channel.")
    inbox_sub = inbox_parser.add_subparsers(dest="action")

    inbox_pull = inbox_sub.add_parser("pull", help="Fetch new channel messages and issue REQ-IDs.")
    inbox_pull.add_argument("--desk", required=True, help="Target desk_id.")
    inbox_pull.add_argument("--prefix", help="Only import messages starting with this prefix.")
    inbox_pull.add_argument("--limit", type=int, default=50, help="Maximum messages to pull.")
    inbox_pull.add_argument("--include-bots", action="store_true", help="Also import bot messages.")
    _add_output_options(inbox_pull)

    # --- req ---
    req_parser = top.add_parser("req", help="Manage requests, questions, replies, and status.")
    req_sub = req_parser.add_subparsers(dest="action")

    req_create = req_sub.add_parser("create", help="Create a new request (or sub-request).")
    req_create.add_argument("--desk", required=True, help="Target desk_id.")
    req_create.add_argument("--title", required=True, help="Short request title.")
    req_create.add_argument("--body", default="", help="Detailed request description.")
    req_create.add_argument("--parent", help="Parent REQ-ID for sub-tasks / delegation.")
    req_create.add_argument("--requester", help="Requester actor_id.")
    req_create.add_argument("--assignee", help="Assignee actor_id.")
    req_create.add_argument("--post", action="store_true", help="Also post the request to the desk channel.")
    req_create.add_argument("--allow-mentions", action="store_true", help="Allow Discord mentions.")
    _add_output_options(req_create)

    req_list = req_sub.add_parser("list", help="List requests.")
    req_list.add_argument("--desk", help="Filter by desk_id.")
    req_list.add_argument("--status", choices=VALID_REQUEST_STATUSES, help="Filter by status.")
    req_list.add_argument("--parent", help="Filter by parent REQ-ID.")
    req_list.add_argument("--assignee", help="Filter by assignee actor_id.")
    req_list.add_argument("--limit", type=int, default=50, help="Maximum requests to show.")
    _add_output_options(req_list)

    req_show = req_sub.add_parser("show", help="Show request details and event history.")
    req_show.add_argument("req_id", help="REQ-ID (e.g. REQ-0001).")
    req_show.add_argument("--events", type=int, default=50, help="Maximum events to include.")
    _add_output_options(req_show)

    req_ask = req_sub.add_parser("ask", help="Create thread if needed and post a question.")
    req_ask.add_argument("req_id", help="REQ-ID.")
    req_ask.add_argument("text", nargs="?", help="Question text.")
    req_ask.add_argument("-m", "--message", help="Question text.")
    req_ask.add_argument("--stdin", action="store_true", help="Read question text from stdin.")
    req_ask.add_argument("--actor", help="Sending actor_id.")
    req_ask.add_argument("--thread-name", help="Custom thread name when creating a new thread.")
    req_ask.add_argument("--allow-mentions", action="store_true", help="Allow Discord mentions.")
    _add_output_options(req_ask)

    req_read = req_sub.add_parser("read", help="Fetch new replies in the request thread.")
    req_read.add_argument("req_id", help="REQ-ID.")
    req_read.add_argument("--author-id", help="Filter by specific external author_id.")
    req_read.add_argument("--any-user", action="store_true", help="Include messages from any user/bot.")
    req_read.add_argument("--limit", type=int, default=50, help="Maximum replies to fetch.")
    _add_output_options(req_read)

    req_wait = req_sub.add_parser("wait", help="Wait for new replies in the request thread.")
    req_wait.add_argument("req_id", help="REQ-ID.")
    req_wait.add_argument("--timeout", type=float, default=60.0, help="Timeout in seconds (default: 60).")
    req_wait.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds (default: 2).")
    req_wait.add_argument("--author-id", help="Filter by specific external author_id.")
    req_wait.add_argument("--any-user", action="store_true", help="Include messages from any user/bot.")
    _add_output_options(req_wait)

    req_reply = req_sub.add_parser("reply", help="Post a reply, progress update, or final report.")
    req_reply.add_argument("req_id", help="REQ-ID.")
    req_reply.add_argument("text", nargs="?", help="Reply text.")
    req_reply.add_argument("-m", "--message", help="Reply text.")
    req_reply.add_argument("--stdin", action="store_true", help="Read reply text from stdin.")
    req_reply.add_argument("--actor", help="Sending actor_id.")
    req_reply.add_argument("--status", choices=VALID_REQUEST_STATUSES, help="Also update request status.")
    req_reply.add_argument("--allow-mentions", action="store_true", help="Allow Discord mentions.")
    _add_output_options(req_reply)

    req_status = req_sub.add_parser("status", help="Update request status.")
    req_status.add_argument("req_id", help="REQ-ID.")
    req_status.add_argument("status", choices=VALID_REQUEST_STATUSES, help="New status.")
    req_status.add_argument("--actor", help="Actor making the change.")
    req_status.add_argument("--note", default="", help="Optional note for the audit log.")
    _add_output_options(req_status)

    return parser


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    adapter: ConversationAdapter | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    stdin: TextIO | None = None,
) -> int:
    out_stream = stdout if stdout is not None else sys.stdout
    err_stream = stderr if stderr is not None else sys.stderr
    in_stream = stdin if stdin is not None else sys.stdin

    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        if not args.group or not getattr(args, "action", None):
            parser.print_help(file=err_stream)
            return int(ExitCode.INVALID_ARGS)

        resolved_adapter: ConversationAdapter = (
            adapter if adapter is not None else DiscordConversationAdapter()
        )
        fmt = args.format

        with SQLiteStore(args.db) as store:
            svc = DeskService(store, resolved_adapter)

            if args.group == "desk":
                if args.action == "add":
                    desk = svc.add_desk(
                        args.desk_id,
                        args.channel,
                        name=args.name,
                        default_assignee_id=args.default_assignee,
                    )
                    print(format_desk(desk, fmt), file=out_stream)
                    return int(ExitCode.OK)
                if args.action == "list":
                    print(format_desks(svc.list_desks(), fmt), file=out_stream)
                    return int(ExitCode.OK)

            if args.group == "actor":
                if args.action == "add":
                    actor = svc.add_actor(
                        args.actor_id,
                        args.role,
                        display_name=args.name,
                        desk_id=args.desk,
                        external_user_id=args.external_user_id,
                    )
                    print(format_actor(actor, fmt), file=out_stream)
                    return int(ExitCode.OK)
                if args.action == "list":
                    print(
                        format_actors(svc.list_actors(desk_id=args.desk, role=args.role), fmt),
                        file=out_stream,
                    )
                    return int(ExitCode.OK)

            if args.group == "inbox" and args.action == "pull":
                pull_res = svc.pull_inbox(
                    args.desk,
                    prefix=args.prefix,
                    limit=args.limit,
                    exclude_bots=not bool(args.include_bots),
                )
                print(format_inbox_pull(pull_res, fmt), file=out_stream)
                return int(ExitCode.OK)

            if args.group == "req":
                if args.action == "create":
                    req = svc.create_request(
                        args.desk,
                        args.title,
                        args.body,
                        parent_req_id=args.parent,
                        requester_actor_id=args.requester,
                        assignee_actor_id=args.assignee,
                        post_to_channel=bool(args.post),
                        allow_mentions=bool(args.allow_mentions),
                    )
                    print(format_request(req, fmt), file=out_stream)
                    return int(ExitCode.OK)

                if args.action == "list":
                    reqs = svc.list_requests(
                        desk_id=args.desk,
                        status=args.status,
                        parent_req_id=args.parent,
                        assignee_actor_id=args.assignee,
                        limit=args.limit,
                    )
                    print(format_requests(reqs, fmt), file=out_stream)
                    return int(ExitCode.OK)

                if args.action == "show":
                    req, events = svc.get_request_detail(args.req_id, event_limit=args.events)
                    print(format_request_detail(req, events, fmt), file=out_stream)
                    return int(ExitCode.OK)

                if args.action == "ask":
                    content = _read_message_arg(args.text, args.message, bool(args.stdin), in_stream)
                    ask_res = svc.ask(
                        args.req_id,
                        content,
                        actor_id=args.actor,
                        thread_name=args.thread_name,
                        allow_mentions=bool(args.allow_mentions),
                    )
                    print(format_ask(ask_res, fmt), file=out_stream)
                    return int(ExitCode.OK)

                if args.action == "read":
                    read_res = svc.read_replies(
                        args.req_id,
                        any_user=bool(args.any_user),
                        author_id=args.author_id,
                        limit=args.limit,
                    )
                    print(format_replies(read_res, fmt), file=out_stream)
                    return int(ExitCode.OK)

                if args.action == "wait":
                    wait_res = svc.wait_for_answer(
                        args.req_id,
                        timeout=args.timeout,
                        poll_interval=args.poll_interval,
                        any_user=bool(args.any_user),
                        author_id=args.author_id,
                    )
                    print(format_replies(wait_res, fmt), file=out_stream)
                    return int(ExitCode.OK)

                if args.action == "reply":
                    content = _read_message_arg(args.text, args.message, bool(args.stdin), in_stream)
                    reply_res = svc.reply(
                        args.req_id,
                        content,
                        actor_id=args.actor,
                        status=args.status,
                        allow_mentions=bool(args.allow_mentions),
                    )
                    print(format_reply(reply_res, fmt), file=out_stream)
                    return int(ExitCode.OK)

                if args.action == "status":
                    updated, _ = svc.set_status(
                        args.req_id,
                        args.status,
                        actor_id=args.actor,
                        note=args.note,
                    )
                    print(format_request(updated, fmt), file=out_stream)
                    return int(ExitCode.OK)

        raise InvalidArgumentsError("Unknown command.")
    except AgentDeskError as exc:
        print(f"[agent-desk] error ({exc.code}): {exc.message}", file=err_stream)
        return exc.exit_code


def main() -> None:
    sys.exit(run_cli())


if __name__ == "__main__":
    main()
