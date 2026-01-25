"""Astrology API client for fetching kundali (birth chart) data."""

import asyncio
import logging
import os
from base64 import b64encode

import httpx
from dateutil import parser as date_parser

logger = logging.getLogger("astrology")

ASTROLOGY_API_BASE_URL = "https://json.astrologyapi.com/v1"


def _get_auth_header() -> str:
    """Get Basic Auth header from environment variables."""
    user_id = os.getenv("ASTROLOGY_API_USER_ID", "")
    api_key = os.getenv("ASTROLOGY_API_KEY", "")
    credentials = f"{user_id}:{api_key}"
    encoded = b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


def _parse_birth_params(
    date_of_birth: str,
    time_of_birth: str,
    latitude: float,
    longitude: float,
    timezone: float,
) -> dict | None:
    """Parse birth details into API request parameters."""
    try:
        # Parse date
        date = date_parser.parse(date_of_birth)
        day = date.day
        month = date.month
        year = date.year

        # Parse time - handle approximate times
        time_str = time_of_birth.lower()

        # Handle approximate times
        time_mapping = {
            "morning": "09:00",
            "noon": "12:00",
            "afternoon": "15:00",
            "evening": "18:00",
            "night": "21:00",
            "midnight": "00:00",
            "dawn": "06:00",
            "dusk": "18:00",
        }

        parsed_time = None
        for keyword, default_time in time_mapping.items():
            if keyword in time_str:
                parsed_time = date_parser.parse(default_time)
                break

        if not parsed_time:
            # Try parsing as a regular time
            parsed_time = date_parser.parse(time_of_birth)

        hour = parsed_time.hour
        minute = parsed_time.minute

        return {
            "day": day,
            "month": month,
            "year": year,
            "hour": hour,
            "min": minute,
            "lat": latitude,
            "lon": longitude,
            "tzone": timezone,
        }
    except Exception as e:
        logger.error(f"Failed to parse birth details: {e}")
        return None


async def _fetch_astro_details(
    client: httpx.AsyncClient, params: dict, auth_header: str
) -> dict | None:
    """Fetch basic astrological details from the API."""
    try:
        response = await client.post(
            f"{ASTROLOGY_API_BASE_URL}/astro_details",
            json=params,
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        return {
            "ascendant": data.get("ascendant", ""),
            "nakshatra": data.get("Nakshatra", ""),
            "nakshatra_lord": data.get("Nakshatra-Lord", ""),
            "varna": data.get("Varna", ""),
            "vashya": data.get("Vashya", ""),
            "yoni": data.get("Yoni", ""),
            "gan": data.get("Gan", ""),
            "nadi": data.get("Nadi", ""),
            "name_start": data.get("name_start", ""),
        }
    except Exception as e:
        logger.error(f"Failed to fetch astro details: {e}")
        return None


async def _fetch_planet_positions(
    client: httpx.AsyncClient, params: dict, auth_header: str
) -> list[dict]:
    """Fetch planet positions from the API."""
    try:
        response = await client.post(
            f"{ASTROLOGY_API_BASE_URL}/planets",
            json=params,
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        planets = []
        for planet_data in data:
            planets.append(
                {
                    "name": planet_data.get("name", ""),
                    "sign": planet_data.get("sign", ""),
                    "house": planet_data.get("house", 0),
                    "degree": planet_data.get("fullDegree", 0.0),
                    "retrograde": planet_data.get("isRetro", "") == "true",
                    "nakshatra": planet_data.get("nakshatra", ""),
                    "nakshatra_lord": planet_data.get("nakshatraLord", ""),
                }
            )
        return planets
    except Exception as e:
        logger.error(f"Failed to fetch planet positions: {e}")
        return []


async def _fetch_current_dasha(
    client: httpx.AsyncClient, params: dict, auth_header: str
) -> dict | None:
    """Fetch current Chardasha from the API."""
    try:
        response = await client.post(
            f"{ASTROLOGY_API_BASE_URL}/current_chardasha",
            json=params,
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        return {
            "major_dasha": {
                "sign_name": data.get("major_dasha", {}).get("sign_name", ""),
                "duration": data.get("major_dasha", {}).get("duration", ""),
                "start_date": data.get("major_dasha", {}).get("start_date", ""),
                "end_date": data.get("major_dasha", {}).get("end_date", ""),
            },
            "sub_dasha": {
                "sign_name": data.get("sub_dasha", {}).get("sign_name", ""),
                "duration": data.get("sub_dasha", {}).get("duration", ""),
                "start_date": data.get("sub_dasha", {}).get("start_date", ""),
                "end_date": data.get("sub_dasha", {}).get("end_date", ""),
            },
        }
    except Exception as e:
        logger.error(f"Failed to fetch current dasha: {e}")
        return None


def _format_kundali(astro: dict, planets: list[dict], dasha: dict | None = None) -> str:
    """Format kundali data as text for LLM context."""
    lines = ["## User's Kundali (Birth Chart)", ""]

    # Astro details
    lines.append("### Basic Details")
    lines.append(f"- Ascendant (Lagna): {astro['ascendant']}")
    lines.append(f"- Nakshatra: {astro['nakshatra']} (Lord: {astro['nakshatra_lord']})")
    lines.append(f"- Varna: {astro['varna']}")
    lines.append(f"- Vashya: {astro['vashya']}")
    lines.append(f"- Yoni: {astro['yoni']}")
    lines.append(f"- Gan: {astro['gan']}")
    lines.append(f"- Nadi: {astro['nadi']}")
    if astro["name_start"]:
        lines.append(f"- Auspicious Name Start: {astro['name_start']}")
    lines.append("")

    # Planet positions
    lines.append("### Planet Positions")
    for planet in planets:
        retro = " (R)" if planet["retrograde"] else ""
        lines.append(
            f"- {planet['name']}: {planet['sign']} in House {planet['house']} "
            f"at {planet['degree']:.1f}°{retro} | "
            f"Nakshatra: {planet['nakshatra']} (Lord: {planet['nakshatra_lord']})"
        )

    # Current Dasha
    if dasha:
        lines.append("")
        lines.append("### Current Dasha")
        major = dasha["major_dasha"]
        sub = dasha["sub_dasha"]
        lines.append(
            f"- Major Dasha: {major['sign_name']} ({major['duration']}, "
            f"{major['start_date']} to {major['end_date']})"
        )
        lines.append(
            f"- Sub Dasha: {sub['sign_name']} ({sub['duration']}, "
            f"{sub['start_date']} to {sub['end_date']})"
        )

    return "\n".join(lines)


async def fetch_kundali(
    date_of_birth: str,
    time_of_birth: str,
    latitude: float,
    longitude: float,
    timezone: float,
) -> str | None:
    """Fetch kundali with pre-computed timezone.

    Args:
        date_of_birth: Date of birth string (e.g., "March 15, 1990")
        time_of_birth: Time of birth string (e.g., "3:30 PM", "morning")
        latitude: Latitude of birth location
        longitude: Longitude of birth location
        timezone: Timezone offset in hours from UTC

    Returns:
        Formatted kundali text, or None if failed.
    """
    auth_header = _get_auth_header()

    # Parse birth details into API params
    params = _parse_birth_params(
        date_of_birth, time_of_birth, latitude, longitude, timezone
    )
    if not params:
        return None

    async with httpx.AsyncClient() as client:
        # Fetch all endpoints in parallel
        astro_task = _fetch_astro_details(client, params, auth_header)
        planets_task = _fetch_planet_positions(client, params, auth_header)
        dasha_task = _fetch_current_dasha(client, params, auth_header)

        astro_details, planets, dasha = await asyncio.gather(
            astro_task, planets_task, dasha_task
        )

        if not astro_details:
            logger.error("Failed to fetch astro details")
            return None

        return _format_kundali(astro_details, planets, dasha)
