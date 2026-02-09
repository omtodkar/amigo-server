"""Tests for UserStore using fakeredis."""

import fakeredis.aioredis
import pytest

from store import MAX_CONVERSATIONS, TTL_SECONDS, UserStore


@pytest.fixture
async def store():
    client = fakeredis.aioredis.FakeRedis()
    s = UserStore(client=client)
    yield s
    await s.close()


@pytest.fixture
def sample_birth():
    return {
        "date_of_birth": "March 15, 1990",
        "time_of_birth": "3:30 PM",
        "latitude": 19.076,
        "longitude": 72.8777,
        "timezone": 5.5,
    }


@pytest.fixture
def sample_kundali():
    return {"planets": {"Sun": "Aries"}, "houses": [1, 2, 3]}


@pytest.fixture
def sample_xray():
    return {"core_identity": "test", "emotional_patterns": "stable"}


async def test_round_trip(store, sample_birth, sample_kundali, sample_xray):
    """Saving and loading returns the same data."""
    await store.save_user_data("user-1", sample_birth, sample_kundali, sample_xray)
    birth, kundali, xray = await store.load_user_data("user-1")
    assert birth == sample_birth
    assert kundali == sample_kundali
    assert xray == sample_xray


async def test_missing_user(store):
    """Loading a non-existent user returns (None, None, None)."""
    birth, kundali, xray = await store.load_user_data("no-such-user")
    assert birth is None
    assert kundali is None
    assert xray is None


async def test_has_user_data_true(store, sample_birth, sample_kundali, sample_xray):
    """has_user_data returns True when birth key exists."""
    await store.save_user_data("user-1", sample_birth, sample_kundali, sample_xray)
    assert await store.has_user_data("user-1") is True


async def test_has_user_data_false(store):
    """has_user_data returns False for non-existent user."""
    assert await store.has_user_data("no-such-user") is False


async def test_has_user_data_partial_birth_only(store, sample_birth):
    """has_user_data returns True when only birth details exist."""
    await store.save_user_data("user-1", birth_details=sample_birth)
    assert await store.has_user_data("user-1") is True


async def test_has_user_data_no_birth(store, sample_kundali):
    """has_user_data returns False when only kundali exists (no birth key)."""
    await store.save_user_data("user-1", kundali_json=sample_kundali)
    assert await store.has_user_data("user-1") is False


async def test_overwrite(store, sample_birth, sample_kundali, sample_xray):
    """Saving again overwrites existing data."""
    await store.save_user_data("user-1", sample_birth, sample_kundali, sample_xray)

    new_xray = {"core_identity": "updated", "emotional_patterns": "dynamic"}
    await store.save_user_data("user-1", personality_xray=new_xray)

    birth, kundali, xray = await store.load_user_data("user-1")
    assert birth == sample_birth  # unchanged
    assert kundali == sample_kundali  # unchanged
    assert xray == new_xray  # updated


async def test_partial_data_birth_only(store, sample_birth):
    """Loading user with only birth details returns (birth, None, None)."""
    await store.save_user_data("user-1", birth_details=sample_birth)
    birth, kundali, xray = await store.load_user_data("user-1")
    assert birth == sample_birth
    assert kundali is None
    assert xray is None


async def test_partial_data_birth_and_kundali(store, sample_birth, sample_kundali):
    """Loading user with birth + kundali returns (birth, kundali, None)."""
    await store.save_user_data(
        "user-1", birth_details=sample_birth, kundali_json=sample_kundali
    )
    birth, kundali, xray = await store.load_user_data("user-1")
    assert birth == sample_birth
    assert kundali == sample_kundali
    assert xray is None


async def test_ttl_set_on_save(store, sample_birth, sample_kundali, sample_xray):
    """Keys have TTL after save."""
    await store.save_user_data("user-1", sample_birth, sample_kundali, sample_xray)

    birth_ttl = await store._redis.ttl("amigo:user:user-1:birth")
    kundali_ttl = await store._redis.ttl("amigo:user:user-1:kundali")
    xray_ttl = await store._redis.ttl("amigo:user:user-1:xray")

    assert 0 < birth_ttl <= TTL_SECONDS
    assert 0 < kundali_ttl <= TTL_SECONDS
    assert 0 < xray_ttl <= TTL_SECONDS


async def test_ttl_refreshed_on_read(store, sample_birth, sample_kundali, sample_xray):
    """Reading data refreshes the TTL."""
    await store.save_user_data("user-1", sample_birth, sample_kundali, sample_xray)

    # Manually reduce TTL to simulate time passing
    await store._redis.expire("amigo:user:user-1:birth", 100)
    await store._redis.expire("amigo:user:user-1:kundali", 100)
    await store._redis.expire("amigo:user:user-1:xray", 100)

    # Read should refresh TTL
    await store.load_user_data("user-1")

    birth_ttl = await store._redis.ttl("amigo:user:user-1:birth")
    kundali_ttl = await store._redis.ttl("amigo:user:user-1:kundali")
    xray_ttl = await store._redis.ttl("amigo:user:user-1:xray")

    # TTL should be refreshed back to full duration
    assert birth_ttl > 100
    assert kundali_ttl > 100
    assert xray_ttl > 100


# --- Conversation tests ---


def _make_conversation(convo_id, title="Test", messages=None):
    return {
        "conversationId": convo_id,
        "createdAt": 1770581180559,
        "title": title,
        "messages": messages
        or [
            {"from": "user", "message": "Hello", "timestamp": 1770580983683},
            {"from": "assistant", "message": "Hi!", "timestamp": 1770580967526},
        ],
    }


async def test_save_and_get_conversations(store):
    """Saving and getting conversations returns the same data."""
    convo = _make_conversation("room-1")
    await store.save_conversation("user-1", convo)
    result = await store.get_conversations("user-1")
    assert len(result) == 1
    assert result[0] == convo


async def test_conversations_most_recent_first(store):
    """Conversations are returned most recent first (LPUSH order)."""
    await store.save_conversation("user-1", _make_conversation("room-1"))
    await store.save_conversation("user-1", _make_conversation("room-2"))
    await store.save_conversation("user-1", _make_conversation("room-3"))
    result = await store.get_conversations("user-1")
    assert [c["conversationId"] for c in result] == ["room-3", "room-2", "room-1"]


async def test_conversations_max_limit(store):
    """Only MAX_CONVERSATIONS are kept in Redis."""
    for i in range(MAX_CONVERSATIONS + 3):
        await store.save_conversation("user-1", _make_conversation(f"room-{i}"))
    result = await store.get_conversations("user-1")
    assert len(result) == MAX_CONVERSATIONS


async def test_conversations_get_with_limit(store):
    """get_conversations respects the limit parameter."""
    for i in range(4):
        await store.save_conversation("user-1", _make_conversation(f"room-{i}"))
    result = await store.get_conversations("user-1", limit=2)
    assert len(result) == 2


async def test_conversations_empty_user(store):
    """Getting conversations for unknown user returns empty list."""
    result = await store.get_conversations("no-such-user")
    assert result == []


async def test_update_conversation(store):
    """Updating appends messages to an existing conversation."""
    convo = _make_conversation("room-1")
    await store.save_conversation("user-1", convo)

    new_msgs = [{"from": "user", "message": "How are you?", "timestamp": 1770581200000}]
    found = await store.update_conversation("user-1", "room-1", new_msgs)
    assert found is True

    result = await store.get_conversations("user-1")
    assert len(result[0]["messages"]) == 3
    assert result[0]["messages"][-1]["message"] == "How are you?"


async def test_update_conversation_not_found(store):
    """Updating a non-existent conversation returns False."""
    found = await store.update_conversation("user-1", "no-such-room", [])
    assert found is False


async def test_conversation_ttl(store):
    """Conversation key has TTL after save."""
    await store.save_conversation("user-1", _make_conversation("room-1"))
    ttl = await store._redis.ttl("amigo:user:user-1:conversations")
    assert 0 < ttl <= TTL_SECONDS


async def test_conversation_ttl_refreshed_on_read(store):
    """Reading conversations refreshes the TTL."""
    await store.save_conversation("user-1", _make_conversation("room-1"))
    await store._redis.expire("amigo:user:user-1:conversations", 100)
    await store.get_conversations("user-1")
    ttl = await store._redis.ttl("amigo:user:user-1:conversations")
    assert ttl > 100
