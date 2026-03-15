"""BDD steps for streaming output behavior."""

from __future__ import annotations

import io
import os
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from pytest_bdd import given, parsers, scenarios, then, when

from agent_diy.__main__ import _stream_response
from agent_diy.core.agent import create_agent

scenarios(str(Path(__file__).resolve().parents[1] / "features" / "streaming.feature"))


@pytest.fixture
def streaming_context():
    return {
        "agent": None,
        "thread_id": "streaming-thread",
        "raw_chunks": [],
        "chunks": [],
        "response": "",
        "tool_calls": [],
        "stream_output": "",
    }


class StreamingFakeModel(BaseChatModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        for token in ["hel", "lo"]:
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=token))
            if run_manager:
                run_manager.on_llm_new_token(token, chunk=chunk)
            yield chunk

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "streaming-fake"


@given("a compiled agent graph")
def given_compiled_agent_graph(streaming_context):
    streaming_context["agent"] = create_agent(model=StreamingFakeModel())


@when(parsers.parse('I call stream() with stream_mode "{mode}"'))
def when_i_call_stream_with_mode(streaming_context, mode):
    chunks = []
    for chunk in streaming_context["agent"].stream(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": streaming_context["thread_id"]}},
        stream_mode=mode,
        version="v2",
    ):
        if isinstance(chunk, tuple) and len(chunk) == 2:
            chunk = {"type": "messages", "data": chunk}
        chunks.append(chunk)
    streaming_context["raw_chunks"] = chunks


@then("the graph should yield message chunks")
def then_graph_should_yield_message_chunks(streaming_context):
    chunks = streaming_context["raw_chunks"]
    assert chunks
    assert any(
        chunk.get("type") == "messages"
        and chunk["data"][1].get("langgraph_node") == "llm_call"
        for chunk in chunks
    )


def _make_chunk(content: str, node: str = "llm_call") -> dict:
    return {
        "type": "messages",
        "data": (AIMessageChunk(content=content), {"langgraph_node": node}),
    }


class MockAgent:
    def stream(self, *args, **kwargs):
        yield _make_chunk("你")
        yield _make_chunk("好")
        yield _make_chunk("！")


class MockToolCallingAgent:
    def stream(self, *args, **kwargs):
        yield {
            "type": "messages",
            "data": (
                AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": "get_current_weather",
                            "args": "",
                            "id": "1",
                            "index": 0,
                        }
                    ],
                ),
                {"langgraph_node": "llm_call"},
            ),
        }
        yield {
            "type": "messages",
            "data": (
                AIMessageChunk(content="北京今天晴，25℃。"),
                {"langgraph_node": "llm_call"},
            ),
        }


class MockEmptyStreamAgent:
    def stream(self, *args, **kwargs):
        if False:
            yield None


class MockNonLlmNodeAgent:
    def stream(self, *args, **kwargs):
        yield _make_chunk("这段应被忽略", node="tools")


@given("a mock streaming agent that yields tokens")
def given_mock_streaming_agent(streaming_context):
    streaming_context["agent"] = MockAgent()


@given("a mock streaming agent that calls a tool")
def given_mock_tool_calling_agent(streaming_context):
    streaming_context["agent"] = MockToolCallingAgent()


@given("a mock streaming agent with empty stream")
def given_mock_empty_stream_agent(streaming_context):
    streaming_context["agent"] = MockEmptyStreamAgent()


@given("a mock streaming agent that yields non-llm chunks")
def given_mock_non_llm_node_agent(streaming_context):
    streaming_context["agent"] = MockNonLlmNodeAgent()


@when("the CLI processes the stream")
def when_cli_processes_stream(streaming_context, capsys):
    streaming_context["stream_output"] = _stream_response(
        streaming_context["agent"],
        {"messages": [HumanMessage(content="测试")]},
        {"configurable": {"thread_id": "streaming-cli"}},
    )
    streaming_context["stdout"] = capsys.readouterr().out


@then("each token chunk should be printed immediately")
def then_each_token_chunk_printed_immediately(streaming_context):
    captured = streaming_context["stdout"]
    assert "你好！" in captured
    assert streaming_context["stream_output"] == "你好！"


@then("a tool status line should be printed before the final response")
def then_tool_status_line_before_final_response(streaming_context):
    captured = streaming_context["stdout"]
    tool_line = "[工具调用: get_current_weather]"
    final_response = "北京今天晴，25℃。"
    assert tool_line in captured
    assert final_response in captured
    assert captured.index(tool_line) < captured.index(final_response)


@then("the streamed response should be empty")
def then_streamed_response_should_be_empty(streaming_context):
    assert streaming_context["stream_output"] == ""


@then("non-llm chunks should be ignored")
def then_non_llm_chunks_should_be_ignored(streaming_context):
    assert streaming_context["stream_output"] == ""


@given("a running streaming agent")
def given_running_streaming_agent(streaming_context):
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        pytest.skip("DASHSCOPE_API_KEY not set")
    model = ChatOpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
    )
    streaming_context["agent"] = create_agent(model=model)


@when(parsers.parse('I stream "{question}"'))
def when_i_stream_question(streaming_context, question):
    streaming_context["last_question"] = question
    streaming_context["chunks"] = []
    streaming_context["response"] = ""
    streaming_context["tool_calls"] = []

    for chunk in streaming_context["agent"].stream(
        {"messages": [HumanMessage(content=question)]},
        config={"configurable": {"thread_id": streaming_context["thread_id"]}},
        stream_mode="messages",
        version="v2",
    ):
        if isinstance(chunk, tuple) and len(chunk) == 2:
            chunk = {"type": "messages", "data": chunk}
        if chunk.get("type") != "messages":
            continue
        msg, metadata = chunk["data"]
        if metadata.get("langgraph_node") != "llm_call":
            continue
        if hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks:
            for tool_call in msg.tool_call_chunks:
                name = tool_call.get("name")
                if name:
                    streaming_context["tool_calls"].append(name)
        elif msg.content:
            streaming_context["chunks"].append(msg.content)
            streaming_context["response"] += msg.content


@then("output tokens should arrive incrementally")
def then_output_tokens_arrive_incrementally(streaming_context):
    assert len(streaming_context["chunks"]) > 1


@then("the final response should be non-empty")
def then_final_response_non_empty(streaming_context):
    assert len(streaming_context["response"].strip()) > 5


@then("a tool status line should appear in the output")
def then_tool_status_line_should_appear(streaming_context):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        _stream_response(
            streaming_context["agent"],
            {"messages": [HumanMessage(content=streaming_context["last_question"])]},
            {"configurable": {"thread_id": f'{streaming_context["thread_id"]}-cli-output'}},
        )
    output = buffer.getvalue()
    assert "[工具调用:" in output


@then("the response should contain weather information")
def then_response_contains_weather_info(streaming_context):
    assert re.search(r"(℃|度|摄氏)", streaming_context["response"])
