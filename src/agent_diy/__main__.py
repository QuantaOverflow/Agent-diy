"""CLI entry point: uv run python -m agent_diy"""

import os
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage

from agent_diy.core.agent import create_agent
from agent_diy.core.model import create_dashscope_model
from agent_diy.utils import parse_stream_chunk


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
        event = parse_stream_chunk(chunk)
        if event is None:
            continue

        if event.type == "tool_call":
            if event.content not in tool_call_announced:
                tool_call_announced.add(event.content)
                print(f"\n[工具调用: {event.content}]", flush=True)
        elif event.type == "token":
            print(event.content, end="", flush=True)
            full_text += event.content

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
