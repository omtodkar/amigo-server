# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Amigo is a Vedic astrology AI voice companion backend built on LiveKit Agents SDK. It runs a voice pipeline (STT → LLM → TTS) that collects a user's birth details, generates their kundali (Vedic birth chart) via external APIs, and provides astrological guidance through natural voice conversation.

## Commands

```bash
uv sync                                                # Install dependencies
uv run python src/agent.py download-files              # Download VAD/turn detector models (first time)
uv run python src/agent.py console                     # Run agent in terminal (direct voice)
uv run python src/agent.py dev                         # Run agent for frontend/telephony
uv run python src/agent.py start                       # Run in production
uv run pytest                                          # Run all tests
uv run pytest tests/test_agent.py::test_offers_assistance  # Run a single test
uv run ruff format                                     # Format code
uv run ruff check                                      # Lint code
```

## Architecture

**Entrypoint**: `src/agent.py` — contains the `Assistant` agent class, `AgentServer` setup, and CLI runner.

The `Assistant` class extends LiveKit's `Agent`. Instructions are loaded from `src/prompts/assistant.md` and augmented with the user's kundali when available. Two function tools are defined:

- `record_birth_details()` — collects birth info incrementally (date, time, place), geocodes location, fetches timezone, then retrieves kundali from AstrologyAPI.com. On success, calls `update_agent()` to inject kundali data into the agent's instructions.
- `request_text_input()` — RPC call to the client for text input when voice transcription is unreliable (e.g., place names).

**Voice pipeline** (configured in `my_agent()`):
- STT: Deepgram Nova-3
- LLM: Google Gemini 2.5 Flash
- TTS: ElevenLabs Flash v2.5
- VAD: Silero (prewarmed in `prewarm()`)
- Turn detection: English model
- Noise cancellation: BVC/BVC-Telephony (auto-selected based on SIP vs. browser)

**Supporting modules**:
- `src/astrology.py` — AstrologyAPI.com client; fetches astro details, planet positions, and current Vimshottari Dasha in parallel, then formats as markdown for LLM context.
- `src/geocoding.py` — Google Maps geocoding (place → lat/lon) and timezone lookup (lat/lon + date → UTC offset). Falls back to longitude-based estimate if `GOOGLE_MAPS_API_KEY` is unset.
- `src/models.py` — `SessionState` dataclass (birth details, coordinates, timezone, kundali text).
- `src/prompts.py` — Loads and caches prompt markdown files from `src/prompts/`.

**Session state**: Conversation history is passed via LiveKit participant metadata. Returning users get a "welcome back" greeting; new users get a fresh greeting.

### Testing

Tests use pytest with pytest-asyncio (`asyncio_mode = "auto"`). Tests follow the LLM-as-judge evaluation pattern:

```python
async with (_llm() as llm, AgentSession(llm=llm) as session):
    await session.start(Assistant())
    result = await session.run(user_input="Hello")
    await result.expect.next_event().is_message(role="assistant").judge(llm, intent="...")
    result.expect.no_more_events()
```

Use TDD when modifying agent behavior (instructions, tools, workflows). Write tests first for desired behavior, then iterate until tests pass.

## Environment

Copy `.env.example` to `.env.local` and set:
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` — LiveKit credentials
- `GOOGLE_API_KEY` — Gemini LLM
- `GOOGLE_MAPS_API_KEY` — Geocoding and timezone lookup
- `DEEPGRAM_API_KEY` — Deepgram STT (set automatically if using LiveKit Cloud)
- `ELEVENLABS_API_KEY` — ElevenLabs TTS
- `ASTROLOGY_API_USER_ID`, `ASTROLOGY_API_KEY` — AstrologyAPI.com
- `AGENT_NAME` — optional agent dispatch name (default: auto-dispatch)

## Development Notes

- `uv` is the exclusive Python package manager. Python target: >=3.10, <3.14. Ruff line-length: 88.
- LiveKit Agents evolves rapidly; use the LiveKit Docs MCP server for current documentation.
- For complex agent workflows, use LiveKit's handoffs and tasks to minimize latency instead of long monolithic prompts. See [workflows docs](https://docs.livekit.io/agents/build/workflows/).
- The `src/agent.py` entrypoint is required by the Dockerfile — keep it as the main module.
