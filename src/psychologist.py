"""Psychologist Agent (Layer C) — Dr. Nova, clinical psychologist persona."""

import contextlib
import json
import logging
import re
from collections.abc import AsyncIterable

from livekit.agents import (
    Agent,
    ChatContext,
    FunctionTool,
    ModelSettings,
    RunContext,
    function_tool,
    get_job_context,
)
from livekit.agents.llm import ChatChunk, ChatMessage, ChoiceDelta, StopResponse

from models import SessionState
from profiler import AstroProfiler
from prompts import load_prompt
from store import UserStore

logger = logging.getLogger("psychologist")


def _summarize_xray(xray: dict) -> str:
    """Build a brief human-readable summary of personality X-Ray for the client."""
    parts = []
    core = xray.get("core_identity", {})
    if core.get("archetype"):
        parts.append(f"Archetype: {core['archetype']}")

    emotional = xray.get("emotional_architecture", {})
    if emotional.get("attachment_style"):
        parts.append(f"Attachment: {emotional['attachment_style']}")

    climate = xray.get("current_psychological_climate", {})
    if climate.get("season_of_life"):
        parts.append(f"Season: {climate['season_of_life']}")
    if climate.get("primary_stressor"):
        parts.append(f"Stressor: {climate['primary_stressor']}")

    domain = xray.get("domain_specific_insight", {})
    if domain.get("topic"):
        parts.append(f"Focus: {domain['topic']}")

    return " · ".join(parts) if parts else ""


# Patch the Google LLM plugin to tag thinking parts in ChatChunk.delta.extra.
# The plugin discards `part.thought`, making thinking indistinguishable from
# regular content. This patch preserves it so llm_node can detect and forward it.
try:
    from livekit.plugins.google.llm import LLMStream as _GoogleLLMStream

    _original_parse_part = _GoogleLLMStream._parse_part

    def _patched_parse_part(self, chunk_id, part):
        chunk = _original_parse_part(self, chunk_id, part)
        if chunk and chunk.delta and getattr(part, "thought", False):
            if chunk.delta.extra is None:
                chunk.delta.extra = {}
            chunk.delta.extra["thought"] = True
        return chunk

    _GoogleLLMStream._parse_part = _patched_parse_part
except Exception:
    logger.debug("Could not patch Google LLM plugin for thinking tokens")

# Hard crisis keywords — always trigger static response regardless of risk level
CRISIS_KEYWORDS = ["kill myself", "end it all", "suicide", "suicidal", "want to die"]
_CRISIS_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in CRISIS_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Softer signals — only trigger when crisis_risk_level is "High"
CRISIS_SOFT_KEYWORDS = [
    "end it",
    "die",
    "no point",
    "can't go on",
    "give up",
    "stop living",
]
_CRISIS_SOFT_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in CRISIS_SOFT_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

CRISIS_RESPONSE = (
    "I hear you, and I'm really glad you told me. What you're feeling is real, "
    "and you deserve support right now. Please reach out to the 988 Suicide and "
    "Crisis Lifeline — call or text 988. They're available 24/7 and can help. "
    "You don't have to go through this alone."
)


class PsychologistAgent(Agent):
    """Clinical psychologist agent that uses a Personality X-Ray as hidden context.

    This agent provides therapy using CBT/IFS techniques, guided by a psychological
    profile derived from the user's data. It never reveals the astrological source
    of its insights.
    """

    def __init__(
        self,
        personality_xray: dict | None = None,
        chat_ctx: ChatContext | None = None,
    ):
        self._personality_xray = personality_xray
        instructions = load_prompt("psychologist.md")
        if personality_xray:
            instructions += (
                "\n\n## Client Profile (Internal - Never Reference Source)\n"
            )
            instructions += json.dumps(personality_xray, indent=2)
        super().__init__(instructions=instructions, chat_ctx=chat_ctx)

    async def on_enter(self) -> None:
        """Generate initial greeting when agent becomes active."""
        await self.session.generate_reply(
            instructions=(
                "Warmly greet the client and invite them to share what's on their mind. "
                "Keep it brief and natural — one or two sentences."
            )
        )

    def _is_high_risk(self) -> bool:
        """Check if the X-Ray assessed crisis_risk_level as High."""
        if not self._personality_xray:
            return False
        climate = self._personality_xray.get("current_psychological_climate", {})
        risk_factors = climate.get("risk_factors", {})
        if not isinstance(risk_factors, dict):
            return False
        return risk_factors.get("crisis_risk_level") == "High"

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        """Two-tier crisis keyword detection.

        Tier 1: Hard keywords (suicide, kill myself, etc.) always trigger
        the static crisis response, regardless of assessed risk level.

        Tier 2: Softer signals (die, end it, no point, etc.) only trigger
        when the X-Ray assessed crisis_risk_level as High — these phrases
        are ambiguous in isolation but concerning for high-risk users.
        """
        user_text = new_message.text_content or ""

        if _CRISIS_PATTERN.search(user_text):
            logger.warning(
                "Hard crisis keyword detected — "
                "bypassing LLM with static crisis response"
            )
            self.session.say(CRISIS_RESPONSE)
            raise StopResponse()

        if self._is_high_risk() and _CRISIS_SOFT_PATTERN.search(user_text):
            logger.warning(
                "Soft crisis keyword detected with High risk level — "
                "bypassing LLM with static crisis response"
            )
            self.session.say(CRISIS_RESPONSE)
            raise StopResponse()

    async def llm_node(
        self,
        chat_ctx: ChatContext,
        tools: list[FunctionTool],
        model_settings: ModelSettings,
    ) -> AsyncIterable[ChatChunk | str]:
        """Override to intercept thinking tokens and stream them to the client."""
        try:
            room = get_job_context().room
        except RuntimeError:
            room = None

        if room:
            participants = list(room.remote_participants.values())
            dest = [p.identity for p in participants] if participants else None
        else:
            dest = None

        async for chunk in Agent.default.llm_node(
            self, chat_ctx, tools, model_settings
        ):
            if (
                isinstance(chunk, ChatChunk)
                and chunk.delta
                and chunk.delta.extra
                and chunk.delta.extra.get("thought")
            ):
                # Forward thinking content to client, don't send to TTS
                if dest and room:
                    thinking_text = chunk.delta.content or ""
                    if thinking_text.strip():
                        with contextlib.suppress(Exception):
                            await room.local_participant.send_text(
                                thinking_text,
                                topic="agent-thinking",
                                destination_identities=dest,
                            )
                # Strip thinking content so TTS doesn't speak it
                chunk = ChatChunk(
                    id=chunk.id,
                    delta=ChoiceDelta(
                        role=chunk.delta.role,
                        content="",
                        tool_calls=chunk.delta.tool_calls,
                    ),
                    usage=chunk.usage,
                )
            yield chunk

    @function_tool()
    async def update_personality_xray(
        self,
        context: RunContext[SessionState],
        new_focus_topic: str,
    ) -> str:
        """Update your understanding of the client when the conversation
        shifts to a specific life area like Career, Love, or Trauma.

        Call this when you notice the client is focusing on a particular
        life domain and you want deeper insight into their patterns
        within that area.

        Args:
            new_focus_topic: The life area to focus on (Career, Love, Trauma, or General)
        """
        state = context.userdata

        if not state.kundali_json:
            logger.warning("Cannot update X-Ray: no kundali data available")
            return "Unable to update profile — client data not yet available."

        logger.info(f"Updating personality X-Ray for topic: {new_focus_topic}")

        from_topic = state.current_focus_topic or "General"
        room = get_job_context().room
        await room.local_participant.set_attributes(
            {
                "lk.agent.stage": "generating_xray",
                "lk.agent.tool": "update_personality_xray",
                "lk.agent.detail": f"{from_topic} → {new_focus_topic}",
            }
        )

        profiler = AstroProfiler()
        try:
            xray = await profiler.generate_xray(
                state.kundali_json, focus_topic=new_focus_topic
            )
        except ValueError as e:
            logger.error(f"Failed to generate X-Ray: {e}")
            return (
                "Profile update encountered an issue. "
                "Continue with current understanding."
            )

        state.personality_xray = xray
        state.current_focus_topic = new_focus_topic

        # Persist updated X-Ray
        if state.user_id:
            try:
                store = UserStore()
                await store.save_user_data(state.user_id, personality_xray=xray)
                logger.info(f"Persisted updated X-Ray for user {state.user_id}")
            except Exception as e:
                logger.warning(f"Failed to persist updated X-Ray: {e}")
            finally:
                await store.close()

        # Send X-Ray summary to client
        xray_summary = _summarize_xray(xray)
        if xray_summary:
            participants = list(room.remote_participants.values())
            if participants:
                with contextlib.suppress(Exception):
                    await room.local_participant.send_text(
                        xray_summary,
                        topic="agent-activity",
                        destination_identities=[p.identity for p in participants],
                    )

        await room.local_participant.set_attributes(
            {"lk.agent.stage": "ready", "lk.agent.tool": "", "lk.agent.detail": ""}
        )

        # Hand off to a new PsychologistAgent with updated X-Ray context
        context.session.update_agent(
            PsychologistAgent(personality_xray=xray, chat_ctx=self.chat_ctx)
        )

        return f"Profile updated for {new_focus_topic} focus."
