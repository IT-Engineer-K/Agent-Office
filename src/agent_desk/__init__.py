"""Agent Desk — Human-centered request desk and conversation workflow library."""

from .adapters import (
    ConversationAdapter,
    DiscordConversationAdapter,
    InMemoryConversationAdapter,
)
from .errors import (
    AdapterError,
    AgentDeskError,
    ChannelNotAllowedError,
    ConflictError,
    ExitCode,
    InvalidArgumentsError,
    NotFoundError,
    StorageError,
)
from .models import (
    Actor,
    ActorRole,
    AskResult,
    CreatedThread,
    Desk,
    EventType,
    InboxPullResult,
    IncomingMessage,
    MessageBatch,
    PostedMessage,
    RepliesResult,
    ReplyResult,
    Request,
    RequestEvent,
    RequestStatus,
    WaitBatch,
)
from .service import DeskService
from .store import SQLiteStore, default_db_path

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "DeskService",
    "SQLiteStore",
    "default_db_path",
    "ConversationAdapter",
    "DiscordConversationAdapter",
    "InMemoryConversationAdapter",
    "Desk",
    "Actor",
    "ActorRole",
    "Request",
    "RequestStatus",
    "RequestEvent",
    "EventType",
    "PostedMessage",
    "CreatedThread",
    "IncomingMessage",
    "MessageBatch",
    "WaitBatch",
    "InboxPullResult",
    "AskResult",
    "RepliesResult",
    "ReplyResult",
    "ExitCode",
    "AgentDeskError",
    "InvalidArgumentsError",
    "NotFoundError",
    "ConflictError",
    "ChannelNotAllowedError",
    "AdapterError",
    "StorageError",
]
