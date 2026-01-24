import json
import logging
import os

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    ChatContext,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    get_job_context,
    room_io,
)
from livekit.plugins import deepgram, elevenlabs, google, noise_cancellation, silero
from livekit.plugins.turn_detector.english import EnglishModel

from astrology import fetch_kundali
from geocoding import geocode_place, get_timezone_offset
from models import SessionState
from prompts import load_prompt

logger = logging.getLogger("agent")

load_dotenv(".env.local")


class Assistant(Agent):
    def __init__(
        self, kundali: str | None = None, chat_ctx: ChatContext | None = None
    ) -> None:
        instructions = load_prompt("assistant.md")
        if kundali:
            instructions += "\n\n" + kundali
        super().__init__(
            instructions=instructions,
            chat_ctx=chat_ctx,
        )

    @function_tool()
    async def record_birth_details(
        self,
        context: RunContext[SessionState],
        date_of_birth: str | None = None,
        time_of_birth: str | None = None,
        place_of_birth: str | None = None,
    ) -> str:
        """Record the user's birth details for astrological reading.

        Call this tool when the user provides their birth information.
        You can call this multiple times as the user provides each piece of information.

        Args:
            date_of_birth: Date of birth (e.g., "March 15, 1990" or "1990-03-15")
            time_of_birth: Time of birth (e.g., "3:30 PM", "around noon", "morning")
            place_of_birth: City and country of birth (e.g., "Mumbai, India")
        """
        state = context.userdata

        # Step 1: Record provided details
        if date_of_birth:
            state.date_of_birth = date_of_birth
            logger.info(f"Recorded date of birth: {date_of_birth}")
        if time_of_birth:
            state.time_of_birth = time_of_birth
            logger.info(f"Recorded time of birth: {time_of_birth}")

        # Step 2: Geocode place -> lat/lon
        if place_of_birth:
            coords = await geocode_place(place_of_birth)
            if not coords:
                logger.warning(f"Failed to geocode {place_of_birth}")
                return f"Could not locate '{place_of_birth}'. Please clarify the city and country."
            state.latitude, state.longitude = coords
            logger.info(f"Geocoded {place_of_birth} to {coords}")

        # Check what's still missing
        missing = []
        if not state.date_of_birth:
            missing.append("date of birth")
        if not state.time_of_birth:
            missing.append("time of birth")
        if state.latitude is None:
            missing.append("place of birth")

        if missing:
            return f"Recorded. Still need: {', '.join(missing)}"

        # Step 3: Fetch timezone (requires lat/lon + date/time)
        timezone = await get_timezone_offset(
            state.latitude, state.longitude, state.date_of_birth, state.time_of_birth
        )
        if timezone is None:
            logger.warning("Failed to fetch timezone")
            return "Could not determine timezone for the birth location. Please verify the place."
        state.timezone = timezone
        logger.info(f"Fetched timezone: {timezone}")

        # Step 4: Fetch kundali (requires all details + timezone)
        logger.info("All birth details collected, fetching kundali...")
        kundali = await fetch_kundali(
            state.date_of_birth,
            state.time_of_birth,
            state.latitude,
            state.longitude,
            state.timezone,
        )
        if not kundali:
            logger.warning("Failed to fetch kundali from API")
            return "Failed to generate kundali. Please verify the birth details are correct."

        state.kundali = kundali
        context.session.update_agent(Assistant(kundali=kundali))
        logger.info("Kundali generated and agent updated")
        return "Kundali generated successfully. You now have access to the user's birth chart."

    @function_tool()
    async def request_text_input(
        self,
        context: RunContext[SessionState],
        field_name: str,
        prompt_message: str,
    ) -> str:
        """Request text input from the user when voice recognition is difficult.

        Call this when you're having trouble understanding specific information
        like place names, spellings, or technical terms.

        Args:
            field_name: The field being requested (e.g., "place_of_birth", "name")
            prompt_message: Message to show the user explaining what to type
        """
        try:
            room = get_job_context().room
            participants = list(room.remote_participants.values())
            if not participants:
                logger.warning("No remote participants found for text input request")
                return ""

            participant = participants[0]

            response = await room.local_participant.perform_rpc(
                destination_identity=participant.identity,
                method="requestTextInput",
                payload=json.dumps(
                    {
                        "field": field_name,
                        "prompt": prompt_message,
                    }
                ),
                response_timeout=60.0,  # Give user time to type
            )

            result = json.loads(response)
            return result.get("text", "")
        except Exception as e:
            logger.warning(f"Text input request failed: {e}")
            return ""


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name=os.getenv("AGENT_NAME"))
async def my_agent(ctx: JobContext):
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # Connect first to access participant metadata
    await ctx.connect()

    # Wait for the user to join
    participant = await ctx.wait_for_participant()

    # Read conversation history from participant metadata
    initial_ctx = None
    if participant.metadata:
        try:
            metadata = json.loads(participant.metadata)
            history = metadata.get("conversation_history", [])
            if history:
                initial_ctx = ChatContext()
                for msg in history:
                    initial_ctx.add_message(role=msg["role"], content=msg["content"])
                logger.info(f"Loaded {len(history)} messages from conversation history")
        except json.JSONDecodeError:
            logger.warning("Failed to parse participant metadata as JSON")

    # Set up a voice AI pipeline using Deepgram STT, Google LLM, ElevenLabs TTS, and LiveKit turn detector
    session = AgentSession[SessionState](
        # Session state for storing birth details and other user data
        userdata=SessionState(),
        # Speech-to-text (STT) using Deepgram directly (bypasses LiveKit inference quota)
        # See all available models at https://docs.livekit.io/agents/models/stt/plugins/deepgram/
        stt=deepgram.STT(model="nova-3", language="en"),
        # A Large Language Model (LLM) is your agent's brain, processing user input and generating a response
        # See all available models at https://docs.livekit.io/agents/models/llm/
        llm=google.LLM(model="gemini-2.5-flash"),
        # Text-to-speech (TTS) is your agent's voice, turning the LLM's text into speech that the user can hear
        # See all available models as well as voice selections at https://docs.livekit.io/agents/models/tts/
        tts=elevenlabs.TTS(model="eleven_flash_v2_5", voice_id="bvN2rlvpvH1mT3gPeNUl"),
        # VAD is used to determine when the user is speaking
        vad=ctx.proc.userdata["vad"],
        # Turn detection uses the English model for context-aware end-of-turn detection
        turn_detection=EnglishModel(),
        # allow the LLM to generate a response while waiting for the end of turn
        # See more at https://docs.livekit.io/agents/build/audio/#preemptive-generation
        preemptive_generation=True,
    )

    # To use a realtime model instead of a voice pipeline, use the following session setup instead.
    # (Note: This is for the OpenAI Realtime API. For other providers, see https://docs.livekit.io/agents/models/realtime/))
    # 1. Install livekit-agents[openai]
    # 2. Set OPENAI_API_KEY in .env.local
    # 3. Add `from livekit.plugins import openai` to the top of this file
    # 4. Use the following session setup instead of the version above
    # session = AgentSession(
    #     llm=openai.realtime.RealtimeModel(voice="marin")
    # )

    # # Add a virtual avatar to the session, if desired
    # # For other providers, see https://docs.livekit.io/agents/models/avatar/
    # avatar = hedra.AvatarSession(
    #   avatar_id="...",  # See https://docs.livekit.io/agents/models/avatar/plugins/hedra
    # )
    # # Start the avatar and wait for it to join
    # await avatar.start(session, room=ctx.room)

    assistant = Assistant(chat_ctx=initial_ctx)

    # Start the session, which initializes the voice pipeline and warms up the models
    await session.start(
        agent=assistant,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )

    # Generate greeting based on whether user has conversation history
    if initial_ctx:
        session.generate_reply(
            instructions="Say a brief welcome back greeting in one short sentence"
        )
    else:
        session.generate_reply(
            instructions="Say a brief friendly greeting in one short sentence"
        )


if __name__ == "__main__":
    cli.run_app(server)
