from dataclasses import dataclass


@dataclass
class SessionState:
    """Session-level state stored in AgentSession.userdata."""

    user_id: str | None = None
    date_of_birth: str | None = None
    time_of_birth: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: float | None = None  # Offset in hours from UTC
    kundali: str | None = None  # Formatted kundali text for LLM context
    kundali_json: dict | None = (
        None  # Structured kundali from fetch_structured_kundali()
    )
    personality_xray: dict | None = None  # Personality X-Ray from AstroProfiler
    current_focus_topic: str = "General"  # Current therapy focus topic
