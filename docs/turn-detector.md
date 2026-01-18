Commit: 3042e77 - fix: Disable turn detector to prevent OOM crashes

Changes:

- Removed turn detector from src/agent.py with TODO comment for restoration
- Removed turn-detector extra from pyproject.toml
- Updated uv.lock (374 lines removed - transformers, huggingface-hub, etc.)

To re-enable later:

1. Change livekit-agents[silero] → livekit-agents[silero,turn-detector] in
   pyproject.toml
2. Add import: from livekit.plugins.turn_detector.multilingual import
   MultilingualModel
3. Add turn_detection=MultilingualModel() to AgentSession
4. Run uv lock && uv sync
