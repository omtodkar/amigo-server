"""Redis-backed persistence for user data across sessions."""

import json
import logging
import os

import redis.asyncio as redis

logger = logging.getLogger("store")

TTL_SECONDS = 90 * 24 * 60 * 60  # 90 days


MAX_CONVERSATIONS = 5


class UserStore:
    """Async Redis client for persisting user birth details, kundali, and X-Ray."""

    def __init__(self, client: redis.Redis | None = None):
        if client is not None:
            self._redis = client
        else:
            url = os.getenv("REDIS_URL", "redis://localhost:6379")
            self._redis = redis.from_url(url)

    def _birth_key(self, user_id: str) -> str:
        return f"amigo:user:{user_id}:birth"

    def _kundali_key(self, user_id: str) -> str:
        return f"amigo:user:{user_id}:kundali"

    def _xray_key(self, user_id: str) -> str:
        return f"amigo:user:{user_id}:xray"

    def _conversations_key(self, user_id: str) -> str:
        return f"amigo:user:{user_id}:conversations"

    async def save_user_data(
        self,
        user_id: str,
        birth_details: dict | None = None,
        kundali_json: dict | None = None,
        personality_xray: dict | None = None,
    ) -> None:
        """Save birth details, kundali, and/or X-Ray for a user with 90-day TTL."""
        pipe = self._redis.pipeline()
        if birth_details is not None:
            pipe.set(
                self._birth_key(user_id),
                json.dumps(birth_details),
                ex=TTL_SECONDS,
            )
        if kundali_json is not None:
            pipe.set(
                self._kundali_key(user_id),
                json.dumps(kundali_json),
                ex=TTL_SECONDS,
            )
        if personality_xray is not None:
            pipe.set(
                self._xray_key(user_id),
                json.dumps(personality_xray),
                ex=TTL_SECONDS,
            )
        await pipe.execute()

    async def load_user_data(
        self, user_id: str
    ) -> tuple[dict | None, dict | None, dict | None]:
        """Load birth details, kundali, and X-Ray for a user. Refreshes TTL.

        Returns (birth_details, kundali_json, personality_xray) — any may be None.
        """
        birth_key = self._birth_key(user_id)
        kundali_key = self._kundali_key(user_id)
        xray_key = self._xray_key(user_id)

        pipe = self._redis.pipeline()
        pipe.get(birth_key)
        pipe.get(kundali_key)
        pipe.get(xray_key)
        birth_raw, kundali_raw, xray_raw = await pipe.execute()

        birth = json.loads(birth_raw) if birth_raw else None
        kundali = json.loads(kundali_raw) if kundali_raw else None
        xray = json.loads(xray_raw) if xray_raw else None

        # Refresh TTL on read
        if birth or kundali or xray:
            pipe = self._redis.pipeline()
            if birth:
                pipe.expire(birth_key, TTL_SECONDS)
            if kundali:
                pipe.expire(kundali_key, TTL_SECONDS)
            if xray:
                pipe.expire(xray_key, TTL_SECONDS)
            await pipe.execute()

        return birth, kundali, xray

    async def has_user_data(self, user_id: str) -> bool:
        """Check if birth details exist for a user."""
        return bool(await self._redis.exists(self._birth_key(user_id)))

    async def save_conversation(self, user_id: str, conversation: dict) -> None:
        """Prepend a conversation to the user's list, keeping at most MAX_CONVERSATIONS."""
        key = self._conversations_key(user_id)
        pipe = self._redis.pipeline()
        pipe.lpush(key, json.dumps(conversation))
        pipe.ltrim(key, 0, MAX_CONVERSATIONS - 1)
        pipe.expire(key, TTL_SECONDS)
        await pipe.execute()

    async def get_conversations(
        self, user_id: str, limit: int = MAX_CONVERSATIONS
    ) -> list[dict]:
        """Return the user's conversations (most recent first)."""
        key = self._conversations_key(user_id)
        raw_items = await self._redis.lrange(key, 0, limit - 1)
        if raw_items:
            await self._redis.expire(key, TTL_SECONDS)
        return [json.loads(item) for item in raw_items]

    async def update_conversation(
        self, user_id: str, conversation_id: str, new_messages: list[dict]
    ) -> bool:
        """Append messages to an existing conversation. Returns True if found."""
        key = self._conversations_key(user_id)
        raw_items = await self._redis.lrange(key, 0, -1)
        for i, raw in enumerate(raw_items):
            convo = json.loads(raw)
            if convo.get("conversationId") == conversation_id:
                convo["messages"].extend(new_messages)
                await self._redis.lset(key, i, json.dumps(convo))
                await self._redis.expire(key, TTL_SECONDS)
                return True
        return False

    async def close(self) -> None:
        """Close the Redis connection."""
        await self._redis.aclose()
