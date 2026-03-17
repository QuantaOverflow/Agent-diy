from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import httpx

from agent_diy.agent_backend import (
    DEFAULT_ERROR_REPLY,
    EMPTY_MESSAGES_REPLY,
    InProcessAgentBackend,
    RemoteHttpAgentBackend,
)


def test_inprocess_backend_returns_last_message_text():
    agent = MagicMock()
    agent.invoke.return_value = {"messages": [MagicMock(content="hello")]}
    backend = InProcessAgentBackend(agent=agent)

    reply = asyncio.run(backend.reply(user_id=123, text="hi"))

    assert reply == "hello"
    kwargs = agent.invoke.call_args.kwargs
    assert kwargs["config"]["configurable"]["thread_id"] == "123"


def test_inprocess_backend_returns_error_on_empty_messages():
    agent = MagicMock()
    agent.invoke.return_value = {"messages": []}
    backend = InProcessAgentBackend(agent=agent)

    reply = asyncio.run(backend.reply(user_id=1, text="hi"))

    assert reply == EMPTY_MESSAGES_REPLY


def test_inprocess_backend_returns_error_on_exception():
    agent = MagicMock()
    agent.invoke.side_effect = RuntimeError("boom")
    backend = InProcessAgentBackend(agent=agent)

    reply = asyncio.run(backend.reply(user_id=1, text="hi"))

    assert reply == DEFAULT_ERROR_REPLY


def test_remote_backend_returns_reply():
    async def _case():
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-Agent-Bridge-Token"] == "token"
            return httpx.Response(200, json={"reply": "remote ok"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        backend = RemoteHttpAgentBackend(
            remote_url="https://local.test/v1/telegram/reply",
            bridge_token="token",
            client=client,
        )
        try:
            reply = await backend.reply(user_id=7, text="hi")
        finally:
            await client.aclose()
        assert reply == "remote ok"

    asyncio.run(_case())


def test_remote_backend_returns_error_on_failure():
    async def _case():
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "bad"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        backend = RemoteHttpAgentBackend(
            remote_url="https://local.test/v1/telegram/reply",
            bridge_token="token",
            client=client,
        )
        try:
            reply = await backend.reply(user_id=7, text="hi")
        finally:
            await client.aclose()
        assert reply == DEFAULT_ERROR_REPLY

    asyncio.run(_case())


def test_remote_backend_returns_error_on_timeout():
    async def _case():
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        backend = RemoteHttpAgentBackend(
            remote_url="https://local.test/v1/telegram/reply",
            bridge_token="token",
            client=client,
        )
        try:
            reply = await backend.reply(user_id=7, text="hi")
        finally:
            await client.aclose()
        assert reply == DEFAULT_ERROR_REPLY

    asyncio.run(_case())
