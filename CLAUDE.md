# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Amigo is an AI companion agent backend built on LiveKit Agents. It uses a voice pipeline with OpenAI (LLM), Cartesia (TTS), and AssemblyAI (STT) via LiveKit Cloud.

## Commands

```bash
# Install dependencies
uv sync

# Download required models (VAD, turn detector) - run before first use
uv run python src/agent.py download-files

# Run agent in terminal (direct voice interaction)
uv run python src/agent.py console

# Run agent for frontend/telephony connections
uv run python src/agent.py dev

# Run in production
uv run python src/agent.py start

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/test_agent.py::test_offers_assistance

# Format code
uv run ruff format

# Lint code
uv run ruff check
```

## Architecture

- **`src/agent.py`**: Main entrypoint containing the `Assistant` agent class and `AgentServer` setup
- **`tests/test_agent.py`**: Eval tests using LiveKit's testing framework with LLM-as-judge pattern

### Agent Structure

The `Assistant` class extends `Agent` and defines the agent's personality via `instructions`. Tools are added using the `@function_tool` decorator.

The `AgentSession` configures the voice pipeline:
- STT (speech-to-text): AssemblyAI
- LLM: OpenAI GPT-4.1-mini
- TTS (text-to-speech): Cartesia Sonic-3
- Turn detection: Multilingual model
- VAD: Silero (prewarmed in `prewarm()`)

### Testing Pattern

Tests use `AgentSession` as an async context manager and the `.judge()` method for LLM-based evaluation:

```python
result = await session.run(user_input="Hello")
await result.expect.next_event().is_message(role="assistant").judge(llm, intent="...")
```

## Environment

Copy `.env.example` to `.env.local` and set:
- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`

## Development Guidelines

- Use TDD when modifying agent behavior (instructions, tools, workflows)
- For complex agents, use handoffs and tasks to minimize latency - see [workflows docs](https://docs.livekit.io/agents/build/workflows/)
- LiveKit Agents evolves rapidly; use the LiveKit Docs MCP server for current documentation
