"""Web search tool powered by Alibaba Cloud IQS."""

from __future__ import annotations

import os

from alibabacloud_iqs20241111 import models
from alibabacloud_iqs20241111.client import Client
from alibabacloud_tea_openapi import models as open_api_models
from langchain_core.tools import tool


def _build_client() -> Client:
    access_key_id = os.getenv("ALIYUN_ACCESS_KEY_ID")
    access_key_secret = os.getenv("ALIYUN_ACCESS_KEY_SECRET")
    if not access_key_id or not access_key_secret:
        raise ValueError("缺少阿里云搜索凭证")

    config = open_api_models.Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        endpoint="iqs.cn-zhangjiakou.aliyuncs.com",
    )
    return Client(config)


@tool
def web_search(query: str) -> str:
    """Search the web for real-time info or explicit '搜/查' requests and return source URLs."""

    try:
        client = _build_client()
        request = models.UnifiedSearchRequest(
            body=models.UnifiedSearchInput(
                query=query,
                time_range="NoLimit",
                contents=models.RequestContents(summary=True),
            )
        )
        response = client.unified_search(request)

        page_items = getattr(getattr(response, "body", None), "page_items", None) or []
        lines = []
        for item in page_items[:5]:
            title = getattr(item, "title", "") or "无标题"
            summary = getattr(item, "summary", "") or ""
            link = getattr(item, "link", "") or ""
            if not link:
                continue
            lines.append(f"{title}：{summary} [来源: {link}]")

        if not lines:
            return "未检索到有效结果。"

        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 - tool should degrade gracefully
        return f"网络搜索暂不可用：{exc}。"
