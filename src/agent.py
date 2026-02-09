import json
import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv(".env.local")

# Ensure Google API key auth is used, not Vertex AI credentials from shell env.
# Must run before importing google.genai (via livekit.plugins.google).
for var in (
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_GENAI_USE_VERTEXAI",
):
    os.environ.pop(var, None)

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AgentTask,
    APIConnectOptions,
    ChatContext,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    get_job_context,
    room_io,
)
from livekit.agents.voice.agent_session import SessionConnectOptions
from livekit.plugins import (
    deepgram,
    elevenlabs,
    google,
    noise_cancellation,
    silero,
)
from livekit.plugins.turn_detector.english import EnglishModel

from astrology import fetch_structured_kundali
from geocoding import geocode_place, get_timezone_offset
from models import SessionState
from profiler import AstroProfiler
from psychologist import PsychologistAgent
from store import UserStore

logger = logging.getLogger("agent")


def _summarize_kundali(kundali: dict) -> str:
    """Build a brief human-readable summary of kundali data for the client."""
    parts = []
    if kundali.get("ascendant"):
        parts.append(f"Ascendant: {kundali['ascendant']}")
    if kundali.get("nakshatra"):
        lord = kundali.get("nakshatra_lord", "")
        parts.append(
            f"Nakshatra: {kundali['nakshatra']}" + (f" (Lord: {lord})" if lord else "")
        )

    # Key planets: Sun, Moon, Mars, Jupiter, Venus
    key_planets = {"Sun", "Moon", "Mars", "Jupiter", "Venus"}
    for planet in kundali.get("planets", []):
        name = planet.get("name", "")
        if name in key_planets:
            sign = planet.get("sign", "")
            house = planet.get("house", "")
            retro = " ℞" if planet.get("isRetro") == "true" else ""
            parts.append(f"{name} in {sign} (House {house}){retro}")

    dasha = kundali.get("dasha", {})
    major = dasha.get("major", {})
    if major.get("planet"):
        parts.append(f"Mahadasha: {major['planet']}")

    return " · ".join(parts) if parts else ""


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


async def _send_activity(room: rtc.Room, text: str) -> None:
    """Send an activity detail message to all remote participants."""
    participants = list(room.remote_participants.values())
    if participants and text:
        try:
            await room.local_participant.send_text(
                text,
                topic="agent-activity",
                destination_identities=[p.identity for p in participants],
            )
        except Exception:
            logger.debug("Failed to send activity to client")


async def set_agent_stage(room: rtc.Room, stage: str, tool: str = "") -> None:
    """Set agent pipeline stage and tool attributes visible to the client."""
    await room.local_participant.set_attributes(
        {
            "lk.agent.stage": stage,
            "lk.agent.tool": tool,
        }
    )


@dataclass
class BirthDetailsResult:
    """Result of the birth detail collection task."""

    date_of_birth: str
    time_of_birth: str
    latitude: float
    longitude: float
    timezone: float


class CollectBirthDetailsTask(AgentTask[BirthDetailsResult]):
    """Task that collects the user's birth details for personalized guidance.

    Collects date of birth, time of birth, and place of birth through
    natural conversation. Geocodes the place and resolves timezone
    automatically. Completes when all details are gathered.
    """

    def __init__(self, chat_ctx=None):
        super().__init__(
            instructions=(
                "You are collecting the user's birth details for personalized guidance. "
                "You need their date of birth, time of birth, and place of birth. "
                "Be conversational and patient. Accept approximate times like 'morning' "
                "or 'around noon'. If voice recognition is struggling with a place name, "
                "use the request_text_input tool to ask the user to type it instead."
            ),
            chat_ctx=chat_ctx,
        )
        self._date_of_birth: str | None = None
        self._time_of_birth: str | None = None
        self._latitude: float | None = None
        self._longitude: float | None = None
        self._timezone: float | None = None

    async def on_enter(self) -> None:
        await self.session.generate_reply(
            instructions=(
                "Ask the user for their birth details — date, time, and place of birth. "
                "Be natural and conversational. You can ask for all three at once or "
                "one at a time."
            )
        )

    @function_tool()
    async def record_birth_details(
        self,
        context: RunContext[SessionState],
        date_of_birth: str | None = None,
        time_of_birth: str | None = None,
        place_of_birth: str | None = None,
    ) -> str:
        """Record the user's birth details for personalized guidance.

        Call this tool when the user provides their birth information.
        You can call this multiple times as the user provides each piece
        of information.

        Args:
            date_of_birth: Date of birth (e.g., "March 15, 1990" or "1990-03-15")
            time_of_birth: Time of birth (e.g., "3:30 PM", "around noon", "morning")
            place_of_birth: City and country of birth (e.g., "Mumbai, India")
        """
        state = context.userdata

        if date_of_birth:
            self._date_of_birth = date_of_birth
            state.date_of_birth = date_of_birth
            logger.info(f"Recorded date of birth: {date_of_birth}")
        if time_of_birth:
            self._time_of_birth = time_of_birth
            state.time_of_birth = time_of_birth
            logger.info(f"Recorded time of birth: {time_of_birth}")

        if place_of_birth:
            room = get_job_context().room
            await set_agent_stage(room, "collecting_birth_details", "geocoding")
            coords = await geocode_place(place_of_birth)
            await set_agent_stage(room, "collecting_birth_details")
            if not coords:
                logger.warning(f"Failed to geocode {place_of_birth}")
                return (
                    f"Could not locate '{place_of_birth}'. "
                    "Please clarify the city and country."
                )
            self._latitude, self._longitude = coords
            state.latitude, state.longitude = coords
            logger.info(f"Geocoded {place_of_birth} to {coords}")

        missing = []
        if not self._date_of_birth:
            missing.append("date of birth")
        if not self._time_of_birth:
            missing.append("time of birth")
        if self._latitude is None:
            missing.append("place of birth")

        if missing:
            return f"Recorded. Still need: {', '.join(missing)}"

        timezone = await get_timezone_offset(
            self._latitude,
            self._longitude,
            self._date_of_birth,
            self._time_of_birth,
        )
        if timezone is None:
            logger.warning("Failed to fetch timezone")
            return (
                "Could not determine timezone for the birth location. "
                "Please verify the place."
            )
        self._timezone = timezone
        state.timezone = timezone
        logger.info(f"Fetched timezone: {timezone}")

        logger.info("All birth details collected")
        self.complete(
            BirthDetailsResult(
                date_of_birth=self._date_of_birth,
                time_of_birth=self._time_of_birth,
                latitude=self._latitude,
                longitude=self._longitude,
                timezone=self._timezone,
            )
        )
        return "All birth details collected successfully."

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
                response_timeout=60.0,
            )

            result = json.loads(response)
            return result.get("text", "")
        except Exception as e:
            logger.warning(f"Text input request failed: {e}")
            return ""


class IntakeAgent(Agent):
    """Intake agent that collects birth details and sets up the therapy session.

    Orchestrates:
    1. CollectBirthDetailsTask — gather date, time, place of birth
    2. fetch_structured_kundali() — get structured chart data from API
    3. AstroProfiler.generate_xray() — translate to psychological profile
    4. Handoff to PsychologistAgent with the X-Ray context
    """

    def __init__(self, chat_ctx: ChatContext | None = None):
        super().__init__(
            instructions=(
                "You help collect birth information for personalized guidance. "
                "Be warm and conversational."
            ),
            chat_ctx=chat_ctx,
        )

    async def on_enter(self) -> None:
        room = get_job_context().room

        # Step 1: Run birth detail collection task
        await set_agent_stage(room, "collecting_birth_details")
        birth = await CollectBirthDetailsTask(chat_ctx=self.chat_ctx)

        user_id = self.session.userdata.user_id
        birth_details = {
            "date_of_birth": birth.date_of_birth,
            "time_of_birth": birth.time_of_birth,
            "latitude": birth.latitude,
            "longitude": birth.longitude,
            "timezone": birth.timezone,
        }

        # Persist birth details immediately so they survive failures below
        if user_id:
            try:
                store = UserStore()
                await store.save_user_data(user_id, birth_details=birth_details)
                logger.info(f"Persisted birth details for {user_id}")
            except Exception as e:
                logger.warning(f"Failed to persist birth details: {e}")
            finally:
                await store.close()

        # Step 2: Fetch structured kundali (Layer A)
        await set_agent_stage(room, "fetching_kundali")
        logger.info("Fetching structured kundali...")
        kundali = await fetch_structured_kundali(
            birth.date_of_birth,
            birth.time_of_birth,
            birth.latitude,
            birth.longitude,
            birth.timezone,
        )

        if not kundali:
            logger.error("Failed to fetch structured kundali")
            await self.session.generate_reply(
                instructions=(
                    "Apologize that there was a technical issue generating "
                    "their profile. Offer to try again or continue without "
                    "personalized insights."
                )
            )
            return

        self.session.userdata.kundali_json = kundali
        logger.info("Structured kundali fetched successfully")

        # Send kundali summary to client
        await _send_activity(room, _summarize_kundali(kundali))

        # Step 3: Generate Personality X-Ray (Layer B)
        await set_agent_stage(room, "generating_xray")
        logger.info("Generating Personality X-Ray...")
        profiler = AstroProfiler()
        try:
            xray = await profiler.generate_xray(kundali)
        except Exception as e:
            logger.error(f"Failed to generate X-Ray: {e}")
            # Persist kundali even if X-Ray fails
            if user_id:
                try:
                    store = UserStore()
                    await store.save_user_data(user_id, kundali_json=kundali)
                    logger.info(f"Persisted kundali (without X-Ray) for {user_id}")
                except Exception as store_err:
                    logger.warning(f"Failed to persist kundali: {store_err}")
                finally:
                    await store.close()
            self.session.update_agent(PsychologistAgent())
            return

        self.session.userdata.personality_xray = xray
        logger.info("Personality X-Ray generated successfully")

        # Send X-Ray summary to client
        await _send_activity(room, _summarize_xray(xray))

        # Persist kundali + X-Ray for returning users
        if user_id:
            try:
                store = UserStore()
                await store.save_user_data(
                    user_id, kundali_json=kundali, personality_xray=xray
                )
                logger.info(f"Persisted kundali + X-Ray for {user_id}")
            except Exception as e:
                logger.warning(f"Failed to persist user data: {e}")
            finally:
                await store.close()

        # Step 4: Handoff to PsychologistAgent (Layer C)
        await set_agent_stage(room, "ready")
        self.session.update_agent(PsychologistAgent(personality_xray=xray))


server = AgentServer()


def prewarm(proc: JobProcess):
    # Clear Vertex AI env vars in forked worker processes too
    for var in (
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
    ):
        os.environ.pop(var, None)
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name=os.getenv("AGENT_NAME"))
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    await ctx.connect()
    participant = await ctx.wait_for_participant()

    # Load conversation history and user ID from participant metadata
    initial_ctx = None
    user_id = None
    if participant.metadata:
        try:
            metadata = json.loads(participant.metadata)
            user_id = metadata.get("user_id")
            history = metadata.get("conversation_history", [])
            if history:
                initial_ctx = ChatContext()
                for msg in history:
                    initial_ctx.add_message(role=msg["role"], content=msg["content"])
                logger.info(f"Loaded {len(history)} messages from conversation history")
        except json.JSONDecodeError:
            logger.warning("Failed to parse participant metadata as JSON")

    tts_provider = os.getenv("TTS_PROVIDER", "elevenlabs")
    if tts_provider == "google":
        tts = google.beta.GeminiTTS(
            voice_name="Kore",
        )
        logger.info("Using Google Gemini TTS")
    else:
        tts = elevenlabs.TTS(model="eleven_flash_v2_5", voice_id="ePiPWpzcHZrcqRzFrgQg")
        logger.info("Using ElevenLabs TTS")

    session = AgentSession[SessionState](
        userdata=SessionState(user_id=user_id),
        stt=deepgram.STT(model="nova-3", language="en"),
        llm=google.LLM(
            model="gemini-2.5-flash",
            thinking_config={"thinking_budget": 1024},
        ),
        tts=tts,
        vad=ctx.proc.userdata["vad"],
        turn_detection=EnglishModel(),
        preemptive_generation=True,
        conn_options=SessionConnectOptions(
            llm_conn_options=APIConnectOptions(
                max_retry=5,
                timeout=30.0,
                retry_interval=3.0,
            ),
        ),
    )

    # Layered cache: skip as many steps as possible for returning users.
    # birth + kundali + xray → skip to PsychologistAgent
    # birth + kundali, no xray → generate X-Ray, skip to PsychologistAgent
    # birth only → fetch kundali + generate X-Ray, skip to PsychologistAgent
    # no data → IntakeAgent (new user)
    agent: Agent
    if user_id:
        try:
            store = UserStore()
            await set_agent_stage(ctx.room, "loading_profile")
            birth, kundali, xray = await store.load_user_data(user_id)

            if birth and kundali and xray:
                # Full cache hit — skip everything
                session.userdata.kundali_json = kundali
                session.userdata.personality_xray = xray
                logger.info(f"Full cache hit for user {user_id}")
                await _send_activity(ctx.room, _summarize_kundali(kundali))
                await _send_activity(ctx.room, _summarize_xray(xray))
                agent = PsychologistAgent(personality_xray=xray, chat_ctx=initial_ctx)
            elif birth and kundali:
                # Have kundali but X-Ray failed last time — regenerate
                session.userdata.kundali_json = kundali
                logger.info(f"Generating X-Ray from cached kundali for {user_id}")
                await set_agent_stage(ctx.room, "generating_xray")
                try:
                    profiler = AstroProfiler()
                    xray = await profiler.generate_xray(kundali)
                    session.userdata.personality_xray = xray
                    await store.save_user_data(user_id, personality_xray=xray)
                    await _send_activity(ctx.room, _summarize_xray(xray))
                    agent = PsychologistAgent(
                        personality_xray=xray, chat_ctx=initial_ctx
                    )
                except Exception as e:
                    logger.warning(f"X-Ray generation failed: {e}")
                    agent = PsychologistAgent(chat_ctx=initial_ctx)
            elif birth:
                # Have birth details but kundali missing — fetch + generate
                logger.info(f"Fetching kundali from cached birth for {user_id}")
                await set_agent_stage(ctx.room, "fetching_kundali")
                kundali = await fetch_structured_kundali(
                    birth["date_of_birth"],
                    birth["time_of_birth"],
                    birth["latitude"],
                    birth["longitude"],
                    birth["timezone"],
                )
                if kundali:
                    session.userdata.kundali_json = kundali
                    await set_agent_stage(ctx.room, "generating_xray")
                    try:
                        profiler = AstroProfiler()
                        xray = await profiler.generate_xray(kundali)
                        session.userdata.personality_xray = xray
                        await store.save_user_data(
                            user_id,
                            kundali_json=kundali,
                            personality_xray=xray,
                        )
                        await _send_activity(ctx.room, _summarize_xray(xray))
                        agent = PsychologistAgent(
                            personality_xray=xray, chat_ctx=initial_ctx
                        )
                    except Exception as e:
                        logger.warning(f"X-Ray generation failed: {e}")
                        await store.save_user_data(user_id, kundali_json=kundali)
                        agent = PsychologistAgent(chat_ctx=initial_ctx)
                else:
                    logger.warning("Kundali fetch failed for cached birth")
                    agent = PsychologistAgent(chat_ctx=initial_ctx)
            elif initial_ctx:
                agent = PsychologistAgent(chat_ctx=initial_ctx)
            else:
                agent = IntakeAgent(chat_ctx=initial_ctx)

            await store.close()
        except Exception as e:
            logger.warning(f"Failed to load user data from store: {e}")
            if initial_ctx:
                agent = PsychologistAgent(chat_ctx=initial_ctx)
            else:
                agent = IntakeAgent(chat_ctx=initial_ctx)
    elif initial_ctx:
        agent = PsychologistAgent(chat_ctx=initial_ctx)
    else:
        agent = IntakeAgent(chat_ctx=initial_ctx)

    await set_agent_stage(ctx.room, "ready")
    await session.start(
        agent=agent,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )


if __name__ == "__main__":
    cli.run_app(server)
