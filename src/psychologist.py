"""Psychologist Agent (Layer C) — Dr. Nova, clinical psychologist persona."""

import json
import logging

from livekit.agents import Agent, ChatContext, RunContext, function_tool

from models import SessionState
from profiler import AstroProfiler
from prompts import load_prompt
from store import UserStore

logger = logging.getLogger("psychologist")


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

        # Hand off to a new PsychologistAgent with updated X-Ray context
        context.session.update_agent(
            PsychologistAgent(personality_xray=xray, chat_ctx=self.chat_ctx)
        )

        return f"Profile updated for {new_focus_topic} focus."
