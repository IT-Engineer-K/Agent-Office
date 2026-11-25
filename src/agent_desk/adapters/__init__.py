"""Conversation adapter implementations for Agent Desk."""

from .base import ConversationAdapter
from .discord import DiscordConversationAdapter
from .memory import InMemoryConversationAdapter

__all__ = [
    "ConversationAdapter",
    "DiscordConversationAdapter",
    "InMemoryConversationAdapter",
]
