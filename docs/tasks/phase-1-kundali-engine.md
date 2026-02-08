# Phase 1: Kundali Engine Enhancement (Layer A)

## Goal

Upgrade `src/astrology.py` to fetch from all required AstrologyAPI.com endpoints and output structured JSON matching the `docs/kundali.json` schema, instead of the current markdown format. Update `SessionState` to carry the new structured data.

## Dependencies

None. This phase has no dependencies on other phases.

## Files to Modify

- `src/astrology.py` — Add new endpoint fetchers, new `fetch_structured_kundali()` function
- `src/models.py` — Add new fields to `SessionState`

## Files to Reference (read-only)

- `docs/kundali.json` — Target output schema (sample structured kundali)
- `docs/architecture.md` lines 68-73 — Lists the 4 required API endpoints

## Implementation

### 1. Add New API Fetchers to `src/astrology.py`

Add these functions alongside the existing ones. All use the same `_parse_birth_params()` and `_get_auth_header()` helpers.

#### `_fetch_planets_extended()`

- Endpoint: `POST /planets/extended`
- This **replaces** the current `/planets` endpoint for structured output
- Returns the full planet data including: `fullDegree`, `normDegree`, `speed`, `signLord`, `nakshatra_pad`, `is_planet_set`, `planet_awastha`
- Return each planet as a dict with all fields from the API response (see `docs/kundali.json` `planets` array for exact shape)

```python
async def _fetch_planets_extended(
    client: httpx.AsyncClient, params: dict, auth_header: str
) -> list[dict]:
    """Fetch extended planet positions from the API."""
    try:
        response = await client.post(
            f"{ASTROLOGY_API_BASE_URL}/planets/extended",
            json=params,
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()  # Returns list of planet dicts directly
    except Exception as e:
        logger.error(f"Failed to fetch extended planets: {e}")
        return []
```

#### `_fetch_full_vdasha()`

- Endpoint: `POST /current_vdasha_all`
- This **replaces** the current `/current_vdasha` endpoint
- Returns the full Vimshottari Dasha hierarchy: `major` -> `minor` -> `sub_minor` -> `sub_sub_minor` -> `sub_sub_sub_minor`
- Each level contains a `planet` context object and a `dasha_period` array
- Return the raw response dict (see `docs/kundali.json` `dasha` object for exact shape)

```python
async def _fetch_full_vdasha(
    client: httpx.AsyncClient, params: dict, auth_header: str
) -> dict | None:
    """Fetch full Vimshottari Dasha hierarchy from the API."""
    try:
        response = await client.post(
            f"{ASTROLOGY_API_BASE_URL}/current_vdasha_all",
            json=params,
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch full vdasha: {e}")
        return None
```

#### `_fetch_general_ascendant_report()`

- Endpoint: `POST /general_ascendant_report`
- This is a **new** endpoint not currently fetched
- Returns an ascendant personality report as a text string
- The API response has an `asc_report` key containing the report text

```python
async def _fetch_general_ascendant_report(
    client: httpx.AsyncClient, params: dict, auth_header: str
) -> str | None:
    """Fetch general ascendant report from the API."""
    try:
        response = await client.post(
            f"{ASTROLOGY_API_BASE_URL}/general_ascendant_report",
            json=params,
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("asc_report", "")
    except Exception as e:
        logger.error(f"Failed to fetch ascendant report: {e}")
        return None
```

### 2. New Main Function: `fetch_structured_kundali()`

Add a new public function with the same signature as `fetch_kundali()` but returning `dict | None`:

```python
async def fetch_structured_kundali(
    date_of_birth: str,
    time_of_birth: str,
    latitude: float,
    longitude: float,
    timezone: float,
) -> dict | None:
    """Fetch structured kundali JSON with extended data from all endpoints.

    Args:
        date_of_birth: Date of birth string (e.g., "March 15, 1990")
        time_of_birth: Time of birth string (e.g., "3:30 PM", "morning")
        latitude: Latitude of birth location
        longitude: Longitude of birth location
        timezone: Timezone offset in hours from UTC

    Returns:
        Structured kundali dict matching docs/kundali.json schema, or None if failed.
    """
    auth_header = _get_auth_header()
    params = _parse_birth_params(date_of_birth, time_of_birth, latitude, longitude, timezone)
    if not params:
        return None

    async with httpx.AsyncClient() as client:
        # Fetch all 4 endpoints in parallel
        astro_result, planets_result, dasha_result, ascendant_result = (
            await asyncio.gather(
                _fetch_astro_details(client, params, auth_header),
                _fetch_planets_extended(client, params, auth_header),
                _fetch_full_vdasha(client, params, auth_header),
                _fetch_general_ascendant_report(client, params, auth_header),
            )
        )

        if not astro_result:
            logger.error("Failed to fetch astro details for structured kundali")
            return None

        # Assemble structured output matching docs/kundali.json schema
        return {
            **astro_result,  # Top-level astro fields (ascendant, Varna, etc.)
            "planets": planets_result,
            "dasha": dasha_result or {},
            "ascendant_report": ascendant_result or "",
        }
```

### 3. Keep Existing Functions

**Do not remove** `fetch_kundali()`, `_format_kundali()`, `_fetch_planet_positions()`, or `_fetch_current_dasha()`. They are still used by the current `Assistant` agent and will be removed in Phase 4 when the integration is complete.

### 4. Update `SessionState` in `src/models.py`

Add three new fields:

```python
@dataclass
class SessionState:
    """Session-level state stored in AgentSession.userdata."""

    date_of_birth: str | None = None
    time_of_birth: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: float | None = None
    kundali: str | None = None  # Existing: formatted kundali text (kept for backward compat)
    kundali_json: dict | None = None  # NEW: structured kundali from fetch_structured_kundali()
    personality_xray: dict | None = None  # NEW: personality X-Ray from AstroProfiler
    current_focus_topic: str = "General"  # NEW: current therapy focus topic
```

## Testing

Create `tests/test_astrology.py` with unit tests:

1. **Test `_parse_birth_params()`** with various date/time formats (already works, just verify)
2. **Test `fetch_structured_kundali()`** with mocked API responses:
   - Mock all 4 HTTP endpoints to return sample data
   - Verify the output dict has the required top-level keys: `ascendant`, `planets`, `dasha`, `ascendant_report`
   - Verify `planets` is a list of dicts with extended fields (`fullDegree`, `normDegree`, `speed`, `signLord`, etc.)
   - Verify `dasha` has the full hierarchy keys: `major`, `minor`, `sub_minor`, `sub_sub_minor`, `sub_sub_sub_minor`
3. **Test failure modes**: When `_fetch_astro_details` fails, function returns `None`. When other endpoints fail, their fields are empty but function still returns a dict.

Use `unittest.mock.AsyncMock` or `pytest-httpx` to mock the HTTP calls.

## Verification

```bash
uv run pytest tests/test_astrology.py -v
uv run ruff format src/astrology.py src/models.py
uv run ruff check src/astrology.py src/models.py
```
