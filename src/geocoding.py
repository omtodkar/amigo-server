import logging
import os
from datetime import datetime

import httpx
from dateutil import parser as date_parser

logger = logging.getLogger("geocoding")

GOOGLE_TIMEZONE_API_URL = "https://maps.googleapis.com/maps/api/timezone/json"


async def get_timezone_offset(
    lat: float, lon: float, date_of_birth: str, time_of_birth: str
) -> float | None:
    """Get timezone offset for location at birth datetime.

    Args:
        lat: Latitude of the location
        lon: Longitude of the location
        date_of_birth: Date of birth string (e.g., "March 15, 1990")
        time_of_birth: Time of birth string (e.g., "3:30 PM", "morning")

    Returns:
        Timezone offset in hours from UTC, or None on failure.
    """
    try:
        # Parse date
        date = date_parser.parse(date_of_birth)

        # Parse time - handle approximate times
        time_str = time_of_birth.lower()
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
            parsed_time = date_parser.parse(time_of_birth)

        birth_datetime = datetime(
            date.year, date.month, date.day, parsed_time.hour, parsed_time.minute
        )
    except Exception as e:
        logger.error(f"Failed to parse date/time for timezone lookup: {e}")
        return None

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        logger.warning(
            "GOOGLE_MAPS_API_KEY not set, falling back to longitude-based estimate"
        )
        return round(lon / 15)

    # Convert birth datetime to Unix timestamp
    timestamp = int(birth_datetime.timestamp())

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                GOOGLE_TIMEZONE_API_URL,
                params={
                    "location": f"{lat},{lon}",
                    "timestamp": timestamp,
                    "key": api_key,
                },
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "OK":
                logger.warning(
                    f"Google TimeZone API returned status: {data.get('status')}"
                )
                return None

            # Calculate total offset: rawOffset + dstOffset (both in seconds)
            raw_offset = data.get("rawOffset", 0)
            dst_offset = data.get("dstOffset", 0)
            total_offset_hours = (raw_offset + dst_offset) / 3600

            logger.info(
                f"Timezone for {lat},{lon}: {data.get('timeZoneId')} "
                f"(offset: {total_offset_hours}h)"
            )
            return total_offset_hours

    except Exception as e:
        logger.error(f"Failed to fetch timezone from Google API: {e}")
        return None


async def geocode_place(place: str) -> tuple[float, float] | None:
    """Geocode a place name to lat/lon using Google Geocode API.

    Args:
        place: A place name (e.g., "Mumbai, India")

    Returns:
        A tuple of (latitude, longitude) or None if geocoding fails.
    """
    api_key = os.getenv("GOOGLE_GEOCODE_API_KEY")
    if not api_key:
        return None

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": place, "key": api_key},
        )
        data = response.json()

        if data["status"] == "OK" and data["results"]:
            location = data["results"][0]["geometry"]["location"]
            return (location["lat"], location["lng"])
        return None
