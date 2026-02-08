# Phase 5: Persist Kundali Data Per User (Redis)

## Goal

Persist kundali and Personality X-Ray data at the user level using Redis, so returning users skip the full intake flow and resume directly with the `PsychologistAgent`. A stable client-generated user ID (UUID stored in `localStorage`) serves as the key.

## Dependencies

- **Phase 1** must be complete (`fetch_structured_kundali()`, `kundali_json` in `SessionState`)
- **Phase 2** must be complete (`AstroProfiler`)
- **Phase 3** must be complete (`PsychologistAgent`)
- **Phase 4** must be complete (`IntakeAgent`, `my_agent()` wiring)

## Files to Create

- `server/src/store.py` — `UserStore` class with Redis persistence
- `server/tests/test_store.py` — unit tests for `UserStore`
- `client/lib/user-id.ts` — `getUserId()` helper with `localStorage`

## Files to Modify

- `server/pyproject.toml` — add `redis[hiredis]` dependency
- `server/src/models.py` — add `user_id` field to `SessionState`
- `server/src/agent.py` — load/save user data in `my_agent()` and `IntakeAgent`
- `server/src/psychologist.py` — save updated xray after `update_personality_xray`
- `server/.env.example` — add `REDIS_URL`
- `client/components/agent/agent-view.tsx` — include `user_id` in participant metadata

## Files to Reference

- `server/src/agent.py` — current `my_agent()`, `IntakeAgent`, `CollectBirthDetailsTask`
- `server/src/psychologist.py` — `PsychologistAgent`, `update_personality_xray` tool
- `server/src/models.py` — current `SessionState` dataclass
- `server/src/profiler.py` — `AstroProfiler`
- `server/.env.example` — current env vars

## Implementation

### 1. Client: Stable User Identity

#### `client/lib/user-id.ts` (create)

Generate a stable UUID on first visit, store in `localStorage` under key `amigo-user-id`.

```typescript
const STORAGE_KEY = "amigo-user-id";

export function getUserId(): string {
  if (typeof window === "undefined") {
    // SSR fallback — should not be used for persistence
    return crypto.randomUUID();
  }

  let userId = localStorage.getItem(STORAGE_KEY);
  if (!userId) {
    userId = crypto.randomUUID();
    localStorage.setItem(STORAGE_KEY, userId);
  }
  return userId;
}
```

#### `client/components/agent/agent-view.tsx` (modify)

When constructing participant metadata for the LiveKit session, include the `user_id` from `getUserId()`:

```typescript
import { getUserId } from "@/lib/user-id";

// Where metadata is constructed for the session:
const metadata = JSON.stringify({
  user_id: getUserId(),
  conversation_history: conversationHistory,
});
```

Find the location where `participantMetadata` or `participant.metadata` is set and add the `user_id` field. The exact insertion point depends on how metadata is currently passed — look for where `conversation_history` is serialized into metadata.

### 2. Server: Redis Persistence Module

#### Add dependency to `pyproject.toml`

Add `redis[hiredis]` to the `[project.dependencies]` array:

```
"redis[hiredis]>=5.0.0",
```

Then run `uv sync` to install.

#### `server/src/store.py` (create)

```python
"""User data persistence via Redis."""

import json
import logging
import os

import redis.asyncio as redis

logger = logging.getLogger("store")

# Data expires after 90 days of inactivity
DEFAULT_TTL_SECONDS = 90 * 24 * 60 * 60  # 7,776,000 seconds


class UserStore:
    """Persists kundali and personality X-Ray data per user in Redis.

    Keys:
        amigo:user:{user_id}:kundali — structured kundali JSON
        amigo:user:{user_id}:xray — personality X-Ray JSON

    Both keys share the same TTL and are refreshed on every read or write.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        self._redis_url = redis_url or os.getenv(
            "REDIS_URL", "redis://localhost:6379"
        )
        self._ttl = ttl_seconds
        self._client: redis.Redis | None = None

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(
                self._redis_url, decode_responses=True
            )
        return self._client

    def _kundali_key(self, user_id: str) -> str:
        return f"amigo:user:{user_id}:kundali"

    def _xray_key(self, user_id: str) -> str:
        return f"amigo:user:{user_id}:xray"

    async def save_user_data(
        self,
        user_id: str,
        kundali_json: dict,
        personality_xray: dict,
    ) -> None:
        """Save kundali and X-Ray data for a user.

        Args:
            user_id: Stable user UUID from the client.
            kundali_json: Structured kundali dict from fetch_structured_kundali().
            personality_xray: Personality X-Ray dict from AstroProfiler.
        """
        client = await self._get_client()
        pipe = client.pipeline()
        pipe.set(
            self._kundali_key(user_id),
            json.dumps(kundali_json),
            ex=self._ttl,
        )
        pipe.set(
            self._xray_key(user_id),
            json.dumps(personality_xray),
            ex=self._ttl,
        )
        await pipe.execute()
        logger.info(f"Saved user data for {user_id}")

    async def load_user_data(
        self, user_id: str
    ) -> tuple[dict | None, dict | None]:
        """Load kundali and X-Ray data for a user.

        Returns a (kundali_json, personality_xray) tuple.
        Either value may be None if not found.

        Also refreshes the TTL on both keys so active users don't expire.
        """
        client = await self._get_client()
        pipe = client.pipeline()
        pipe.get(self._kundali_key(user_id))
        pipe.get(self._xray_key(user_id))
        kundali_raw, xray_raw = await pipe.execute()

        kundali = json.loads(kundali_raw) if kundali_raw else None
        xray = json.loads(xray_raw) if xray_raw else None

        # Refresh TTL on access
        if kundali_raw or xray_raw:
            pipe = client.pipeline()
            if kundali_raw:
                pipe.expire(self._kundali_key(user_id), self._ttl)
            if xray_raw:
                pipe.expire(self._xray_key(user_id), self._ttl)
            await pipe.execute()

        return kundali, xray

    async def has_user_data(self, user_id: str) -> bool:
        """Check whether a user has persisted kundali data."""
        client = await self._get_client()
        return bool(await client.exists(self._kundali_key(user_id)))

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None
```

### 3. Server: Update `SessionState` in `src/models.py`

Add a `user_id` field:

```python
@dataclass
class SessionState:
    """Session-level state stored in AgentSession.userdata."""

    user_id: str | None = None  # Stable user UUID from the client
    date_of_birth: str | None = None
    time_of_birth: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: float | None = None
    kundali: str | None = None
    kundali_json: dict | None = None
    personality_xray: dict | None = None
    current_focus_topic: str = "General"
```

### 4. Server: Wire Persistence into `agent.py`

#### Import `UserStore`

Add at the top of `agent.py`:

```python
from store import UserStore
```

#### Update `my_agent()` — load persisted data for returning users

Replace the current routing logic at the bottom of `my_agent()`:

```python
# Currently:
if initial_ctx:
    agent = PsychologistAgent(chat_ctx=initial_ctx)
else:
    agent = IntakeAgent(chat_ctx=initial_ctx)
```

With:

```python
# Extract user_id from participant metadata
user_id = None
if participant.metadata:
    try:
        metadata = json.loads(participant.metadata)
        user_id = metadata.get("user_id")
    except json.JSONDecodeError:
        pass

state = SessionState(user_id=user_id)

# Try to load persisted data for returning users
if user_id:
    store = UserStore()
    try:
        kundali_json, personality_xray = await store.load_user_data(user_id)
    finally:
        await store.close()

    if kundali_json and personality_xray:
        state.kundali_json = kundali_json
        state.personality_xray = personality_xray
        logger.info(f"Loaded persisted data for user {user_id}")
        agent = PsychologistAgent(
            personality_xray=personality_xray, chat_ctx=initial_ctx
        )
    else:
        agent = IntakeAgent(chat_ctx=initial_ctx)
else:
    agent = IntakeAgent(chat_ctx=initial_ctx)
```

**Note:** The `metadata` variable is already parsed earlier in `my_agent()` for `conversation_history`. Reuse that parsed dict rather than parsing twice. The full refactored flow:

```python
metadata = {}
initial_ctx = None
if participant.metadata:
    try:
        metadata = json.loads(participant.metadata)
        history = metadata.get("conversation_history", [])
        if history:
            initial_ctx = ChatContext()
            for msg in history:
                initial_ctx.add_message(role=msg["role"], content=msg["content"])
            logger.info(
                f"Loaded {len(history)} messages from conversation history"
            )
    except json.JSONDecodeError:
        logger.warning("Failed to parse participant metadata as JSON")

user_id = metadata.get("user_id")
state = SessionState(user_id=user_id)

# ... AgentSession creation uses `state` instead of `SessionState()` ...

session = AgentSession[SessionState](
    userdata=state,  # <-- changed from SessionState()
    # ... rest unchanged ...
)

# Route to the correct starting agent
if user_id:
    store = UserStore()
    try:
        kundali_json, personality_xray = await store.load_user_data(user_id)
    finally:
        await store.close()

    if kundali_json and personality_xray:
        state.kundali_json = kundali_json
        state.personality_xray = personality_xray
        logger.info(f"Loaded persisted data for user {user_id}")
        agent = PsychologistAgent(
            personality_xray=personality_xray, chat_ctx=initial_ctx
        )
    else:
        agent = IntakeAgent(chat_ctx=initial_ctx)
else:
    agent = IntakeAgent(chat_ctx=initial_ctx)
```

#### Update `IntakeAgent.on_enter()` — save after generating kundali + xray

After step 3 (generate X-Ray) and before step 4 (handoff), add persistence:

```python
# After: self.session.userdata.personality_xray = xray

# Persist for future sessions
user_id = self.session.userdata.user_id
if user_id:
    store = UserStore()
    try:
        await store.save_user_data(user_id, kundali, xray)
        logger.info(f"Persisted kundali + xray for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to persist user data: {e}")
    finally:
        await store.close()

# Step 4: Handoff to PsychologistAgent (Layer C)
self.session.update_agent(
    PsychologistAgent(personality_xray=xray, chat_ctx=self.chat_ctx)
)
```

### 5. Server: Save Updated X-Ray in `psychologist.py`

In `PsychologistAgent.update_personality_xray()`, after the X-Ray is regenerated and stored in session state, persist it to Redis.

Add `from store import UserStore` at the top of `psychologist.py`.

After `state.personality_xray = xray` (line 81), add:

```python
# Persist updated X-Ray
user_id = state.user_id
if user_id:
    store = UserStore()
    try:
        if state.kundali_json:
            await store.save_user_data(user_id, state.kundali_json, xray)
            logger.info(f"Persisted updated xray for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to persist updated xray: {e}")
    finally:
        await store.close()
```

### 6. Environment Setup

#### `server/.env.example` (modify)

Add after the existing variables:

```
# Redis - for persisting user data across sessions
# Default: redis://localhost:6379
REDIS_URL=redis://localhost:6379
```

## Testing

### `server/tests/test_store.py` (create)

Use `fakeredis` for unit tests (no real Redis required). Add `fakeredis[lua]` as a dev dependency in `pyproject.toml` under `[project.optional-dependencies]` or `[tool.uv.dev-dependencies]`.

```python
"""Tests for the UserStore persistence layer."""

import pytest
import fakeredis.aioredis

from store import UserStore


SAMPLE_KUNDALI = {
    "ascendant": "Virgo",
    "planets": [{"name": "Sun", "sign": "Pisces", "fullDegree": 350.5}],
    "dasha": {"major": {"planet": "Saturn"}},
    "ascendant_report": "Analytical and detail-oriented.",
}

SAMPLE_XRAY = {
    "core_identity": {"archetype": "The Analyst"},
    "emotional_architecture": {"attachment_style": "Secure"},
    "therapist_cheat_sheet": {"recommended_modality": "CBT"},
}


@pytest.fixture
async def store():
    """Create a UserStore backed by fakeredis."""
    s = UserStore()
    s._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_save_and_load(store: UserStore) -> None:
    """Round-trip: save data then load it back."""
    user_id = "test-user-123"

    await store.save_user_data(user_id, SAMPLE_KUNDALI, SAMPLE_XRAY)
    kundali, xray = await store.load_user_data(user_id)

    assert kundali == SAMPLE_KUNDALI
    assert xray == SAMPLE_XRAY


@pytest.mark.asyncio
async def test_load_missing_user(store: UserStore) -> None:
    """Loading a non-existent user returns (None, None)."""
    kundali, xray = await store.load_user_data("nonexistent")

    assert kundali is None
    assert xray is None


@pytest.mark.asyncio
async def test_has_user_data(store: UserStore) -> None:
    """has_user_data returns True only when data exists."""
    user_id = "test-user-456"

    assert not await store.has_user_data(user_id)

    await store.save_user_data(user_id, SAMPLE_KUNDALI, SAMPLE_XRAY)

    assert await store.has_user_data(user_id)


@pytest.mark.asyncio
async def test_overwrite_existing_data(store: UserStore) -> None:
    """Saving again overwrites previous data."""
    user_id = "test-user-789"
    updated_xray = {**SAMPLE_XRAY, "core_identity": {"archetype": "The Healer"}}

    await store.save_user_data(user_id, SAMPLE_KUNDALI, SAMPLE_XRAY)
    await store.save_user_data(user_id, SAMPLE_KUNDALI, updated_xray)

    _, xray = await store.load_user_data(user_id)
    assert xray["core_identity"]["archetype"] == "The Healer"


@pytest.mark.asyncio
async def test_ttl_is_set(store: UserStore) -> None:
    """Verify that keys have a TTL after save."""
    user_id = "test-user-ttl"

    await store.save_user_data(user_id, SAMPLE_KUNDALI, SAMPLE_XRAY)

    client = await store._get_client()
    ttl = await client.ttl(store._kundali_key(user_id))
    assert ttl > 0
```

## Verification

```bash
# 1. Install dependencies
uv sync

# 2. Start local Redis (pick one)
redis-server
# or
docker run -p 6379:6379 redis

# 3. Run store tests
uv run pytest tests/test_store.py -v

# 4. Run all existing tests (should still pass)
uv run pytest tests/ -v

# 5. Manual test flow:
#    a. Start the agent: uv run python src/agent.py dev
#    b. Connect from the client, complete intake (give birth details)
#    c. Verify kundali + xray are persisted:
#       redis-cli GET "amigo:user:<your-uuid>:kundali" | python -m json.tool
#       redis-cli GET "amigo:user:<your-uuid>:xray" | python -m json.tool
#    d. Disconnect and reconnect — agent should skip intake and start PsychologistAgent
#    e. Shift conversation topic — verify updated xray is saved to Redis

# 6. Lint/format
uv run ruff format src/store.py src/agent.py src/psychologist.py src/models.py
uv run ruff check src/store.py src/agent.py src/psychologist.py src/models.py
```

## Rollback Plan

- Redis persistence is additive — if Redis is unavailable, the `try/except/finally` blocks in `IntakeAgent.on_enter()` and `PsychologistAgent.update_personality_xray()` will log errors but not crash the agent.
- If `REDIS_URL` is not set and no Redis is running, `UserStore` will fail to connect. The agent will fall through to `IntakeAgent` for every session (same as current behavior).
- To fully revert: remove `store.py`, remove the `user_id` field from `SessionState`, and restore the original routing logic in `my_agent()`.
