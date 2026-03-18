"""CLI entry point: uv run python -m agent_diy"""

import os
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage

from agent_diy.core.agent import create_agent
from agent_diy.core.model import create_dashscope_model


def _load_dotenv():
    """Load .env file from project root if it exists."""
    env_file = Path.cwd() / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _stream_response(agent, messages_input: dict, config: dict) -> str:
    """Stream agent response to stdout. Returns full response text."""
    tool_call_announced: set[str] = set()
    full_text = ""

    for chunk in agent.stream(
        messages_input,
        config=config,
        stream_mode="messages",
        version="v2",
    ):
        if isinstance(chunk, tuple) and len(chunk) == 2:
            msg, metadata = chunk
        elif isinstance(chunk, dict) and chunk.get("type") == "messages":
            msg, metadata = chunk["data"]
        else:
            continue
        node = metadata.get("langgraph_node", "")

        if node == "llm_call":
            if hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks:
                for tc in msg.tool_call_chunks:
                    name = tc.get("name")
                    if name and name not in tool_call_announced:
                        tool_call_announced.add(name)
                        print(f"\n[工具调用: {name}]", flush=True)
            elif msg.content:
                print(msg.content, end="", flush=True)
                full_text += msg.content

    print()
    return full_text


def main():
    _load_dotenv()
    try:
        model = create_dashscope_model()
    except ValueError:
        print("Error: DASHSCOPE_API_KEY not set")
        sys.exit(1)

    agent = create_agent(model=model)
    config = {"configurable": {"thread_id": "cli-session"}}

    print("Agent ready. Type 'quit' to exit.\n")
    while True:
        try:
            user_input = input("You: ")
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if user_input.strip().lower() in ("quit", "exit"):
            print("Bye!")
            break

        print("Agent: ", end="", flush=True)
        _stream_response(agent, {"messages": [HumanMessage(content=user_input)]}, config)


if __name__ == "__main__":
    main()
