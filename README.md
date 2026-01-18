# Amigo

An AI companion agent backend built on top of [LiveKit Agents](https://github.com/livekit/agents).

## Features

- Voice AI pipeline with OpenAI (LLM), Cartesia (TTS), and AssemblyAI (STT) via LiveKit Cloud
- Multilingual turn detection for natural conversation flow
- Background voice cancellation
- Production-ready Dockerfile

## Setup

Install dependencies:

```console
uv sync
```

Copy `.env.example` to `.env.local` and set your LiveKit credentials:

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`

Or use the [LiveKit CLI](https://docs.livekit.io/home/cli/cli-setup):

```bash
lk cloud auth
lk app env -w -d .env.local
```

## Running

Download required models (first time only):

```console
uv run python src/agent.py download-files
```

Run in terminal:

```console
uv run python src/agent.py console
```

Run for frontend/telephony:

```console
uv run python src/agent.py dev
```

Production:

```console
uv run python src/agent.py start
```

## Tests

```console
uv run pytest
```

## Deployment

This project includes a production-ready `Dockerfile`. See the [deployment guide](https://docs.livekit.io/agents/ops/deployment/) for details.

## License

MIT License - see [LICENSE](LICENSE) for details.
