from dataclasses import dataclass


@dataclass
class SessionState:
    """Session-level state stored in AgentSession.userdata."""

    date_of_birth: str | None = None
    time_of_birth: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: float | None = None  # Offset in hours from UTC
    kundali: str | None = None  # Formatted kundali text for LLM context
