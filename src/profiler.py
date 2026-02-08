"""Astro-Profiler: translates structured kundali JSON into a Personality X-Ray."""

import json
import logging

from livekit.agents.llm import ChatContext
from livekit.plugins import google

from prompts import load_prompt

logger = logging.getLogger("profiler")

# Required top-level keys in the output X-Ray JSON
XRAY_REQUIRED_KEYS = {
    "core_identity",
    "emotional_architecture",
    "cognitive_processing",
    "current_psychological_climate",
    "domain_specific_insight",
    "therapist_cheat_sheet",
}


class AstroProfiler:
    """Translates structured kundali data into a psychological Personality X-Ray.

    Uses a single LLM call to convert astrological data into pure psychology,
    with zero astrological vocabulary in the output.
    """

    def __init__(self) -> None:
        self._llm = google.LLM(model="gemini-2.0-flash")

    async def generate_xray(
        self,
        kundali_json: dict,
        focus_topic: str = "General",
    ) -> dict:
        """Generate a Personality X-Ray from structured kundali data.

        Args:
            kundali_json: Structured kundali dict from fetch_structured_kundali()
            focus_topic: Life area to focus on (General, Career, Love, Trauma)

        Returns:
            Dict matching the personality-x-ray-schema.json structure.

        Raises:
            ValueError: If the LLM output is not valid JSON or missing required keys.
        """
        prompt = load_prompt("profiler.md")

        # Build the chat context with the profiler prompt + kundali data
        chat_ctx = ChatContext()
        chat_ctx.add_message(
            role="system",
            content=prompt,
        )
        chat_ctx.add_message(
            role="user",
            content=(
                f"Focus Topic: {focus_topic}\n\n"
                f"Kundali Data:\n```json\n{json.dumps(kundali_json, indent=2)}\n```"
            ),
        )

        # Single LLM call to translate astrology -> psychology
        # LLM.chat() returns an LLMStream; iterate to collect full text
        stream = self._llm.chat(chat_ctx=chat_ctx)
        chunks = []
        async for text in stream.to_str_iterable():
            chunks.append(text)
        await stream.aclose()
        response_text = "".join(chunks)

        # Parse JSON from response (handle markdown code fences)
        json_text = response_text
        if "```json" in json_text:
            json_text = json_text.split("```json", 1)[1]
            json_text = json_text.split("```", 1)[0]
        elif "```" in json_text:
            json_text = json_text.split("```", 1)[1]
            json_text = json_text.split("```", 1)[0]

        try:
            xray = json.loads(json_text.strip())
        except json.JSONDecodeError as e:
            logger.error("Failed to parse profiler response as JSON: %s", e)
            logger.debug("Raw response: %s", response_text)
            raise ValueError(f"Profiler returned invalid JSON: {e}") from e

        # Validate required keys exist
        missing_keys = XRAY_REQUIRED_KEYS - set(xray.keys())
        if missing_keys:
            logger.error("Profiler output missing keys: %s", missing_keys)
            raise ValueError(f"Profiler output missing required keys: {missing_keys}")

        # Validate new diagnostic fields (warn, don't fail — graceful degradation)
        climate = xray.get("current_psychological_climate", {})
        for field in ("primary_symptom_match", "somatic_signature", "risk_factors"):
            if field not in climate:
                logger.warning(
                    "Profiler output missing diagnostic field: "
                    "current_psychological_climate.%s",
                    field,
                )

        risk_factors = climate.get("risk_factors")
        if isinstance(risk_factors, dict):
            level = risk_factors.get("crisis_risk_level")
            if level not in ("Low", "Medium", "High"):
                logger.warning(
                    "Invalid crisis_risk_level '%s'; expected Low, Medium, or High",
                    level,
                )
        elif risk_factors is not None:
            logger.warning(
                "risk_factors should be a dict, got %s", type(risk_factors).__name__
            )

        return xray
