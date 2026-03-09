"""Shared fixtures for conversation tests."""

from __future__ import annotations

import re

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent_diy.core import agent as agent_module


class FakeModel:
    """Simple deterministic fake model for conversation tests."""

    def invoke(self, messages):
        human_messages = [m for m in messages if isinstance(m, HumanMessage)]
        last_human = human_messages[-1].content if human_messages else ""

        if "what is my name" in last_human.lower():
            name = self._find_latest_name(human_messages)
            if name:
                return AIMessage(content=f"Your name is {name}.")
            return AIMessage(content="I don't know your name yet.")

        intro_match = re.search(r"my name is\s+([A-Za-z]+)", last_human, flags=re.IGNORECASE)
        if intro_match:
            name = intro_match.group(1)
            return AIMessage(content=f"Nice to meet you, {name}.")

        return AIMessage(content="How can I help?")

    @staticmethod
    def _find_latest_name(human_messages):
        # This intentionally scans all human messages in the current state.
        # In these tests, LangGraph's InMemorySaver restores prior turns into
        # `messages` for the same thread_id before invoke(), so name recall
        # depends on that persisted-history behavior.
        for msg in reversed(human_messages):
            match = re.search(r"my name is\s+([A-Za-z]+)", msg.content, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        return None


@pytest.fixture
def patch_init_chat_model(monkeypatch):
    """Patch chat model initialization to avoid external API calls."""

    def _init_chat_model(_model_name):
        return FakeModel()

    monkeypatch.setattr(agent_module, "init_chat_model", _init_chat_model)
