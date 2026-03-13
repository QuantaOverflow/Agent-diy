"""Unit tests for MCP client recovery behavior."""

from __future__ import annotations

import asyncio

from agent_diy.mcp import client as client_module


class _FakeTool:
    def __init__(self, name, fail=False, result=None):
        self.name = name
        self._fail = fail
        self._result = result if result is not None else []
        self.calls = 0

    async def ainvoke(self, _kwargs):
        self.calls += 1
        if self._fail:
            raise RuntimeError("stale session")
        return self._result


def test_invoke_tool_with_recovery_reloads_after_failure(monkeypatch):
    stale = _FakeTool("stock_news", fail=True)
    fresh = _FakeTool("stock_news", fail=False, result=[{"title": "ok"}])
    sequence = [[stale], [fresh]]

    async def _fake_get_tools():
        return sequence.pop(0)

    monkeypatch.setattr(client_module, "get_financial_news_tools", _fake_get_tools)

    result = asyncio.run(
        client_module._invoke_tool_with_recovery("stock_news", {"ticker": "603516"})
    )

    assert result == [{"title": "ok"}]
    assert stale.calls == 1
    assert fresh.calls == 1
