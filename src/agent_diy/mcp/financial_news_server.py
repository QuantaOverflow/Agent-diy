"""MCP server wrapping financial-news HTTP APIs."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP

mcp = FastMCP("financial_news")


def _base_url() -> str:
    value = os.getenv("FINANCIAL_NEWS_BASE_URL")
    if value and value.strip():
        return value.strip().rstrip("/")
    return "http://localhost:8000"


def _as_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("results", "data", "items", "news"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _get(path: str, params: dict | None = None) -> list[dict]:
    try:
        with httpx.Client(timeout=10.0, trust_env=False) as client:
            response = client.get(f"{_base_url()}{path}", params=params)
            response.raise_for_status()
            return _as_list(response.json())
    except Exception:  # noqa: BLE001 - tool should degrade gracefully
        return []


def _post(path: str, body: dict) -> list[dict]:
    try:
        with httpx.Client(timeout=10.0, trust_env=False) as client:
            response = client.post(f"{_base_url()}{path}", json=body)
            response.raise_for_status()
            return _as_list(response.json())
    except Exception:  # noqa: BLE001 - tool should degrade gracefully
        return []


@mcp.tool
def lookup(query: str) -> list[dict]:
    """Lookup ticker/company matches by query."""
    return _get("/api/v1/stock/lookup", {"query": query})


@mcp.tool
def stock_news(symbol: str, limit: int = 15) -> list[dict]:
    """Fetch stock news by stock symbol (e.g. '603516' or '603516.SH')."""
    resolved = symbol.strip().split(".")[0]  # strip exchange suffix if present
    if not resolved.isdigit():
        return []
    return _get("/api/v1/stock/news", {"ticker": resolved, "limit": limit})


@mcp.tool
def semantic_search(query: str, limit: int = 15) -> list[dict]:
    """Run semantic vector search on financial news."""
    return _post("/api/v1/search", {"query": query, "top_k": limit})


@mcp.tool
def hot_news() -> list[dict]:
    """Fetch latest market hot news."""
    return _get("/api/v1/market/hot_news")


if __name__ == "__main__":
    mcp.run()
