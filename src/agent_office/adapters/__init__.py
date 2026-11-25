"""Conversation adapter implementations for Agent Office."""

from .base import ConversationAdapter
from .discord import DiscordConversationAdapter
from .memory import InMemoryConversationAdapter

__all__ = [
    "ConversationAdapter",
    "DiscordConversationAdapter",
    "InMemoryConversationAdapter",
]
