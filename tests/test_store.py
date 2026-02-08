"""Tests for UserStore using fakeredis."""

import fakeredis.aioredis
import pytest

from store import TTL_SECONDS, UserStore


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
