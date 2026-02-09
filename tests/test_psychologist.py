import pytest
from livekit.agents import AgentSession, llm
from livekit.plugins import google

from models import SessionState
from psychologist import PsychologistAgent

SAMPLE_XRAY = {
    "core_identity": {
        "archetype": "The Reluctant King",
        "self_esteem_source": "Being needed, respected, and seen as competent.",
        "shadow_self": "Deep fear of irrelevance. Masks insecurity with workaholism.",
    },
    "emotional_architecture": {
        "attachment_style": "Dismissive-Avoidant",
        "regulation_strategy": "Suppression and 'Doing'. Will try to work their way out of feelings.",
        "vulnerability_trigger": "Public failure or feeling 'useless'.",
    },
    "cognitive_processing": {
        "thinking_style": "Hyper-Analytical loop.",
        "anxiety_loop_pattern": "Rumination on past conversations (Replaying the tape).",
        "learning_modality": "Logical/Structured. Responds to lists and plans.",
    },
    "current_psychological_climate": {
        "season_of_life": "The Deep Winter (Restructuring).",
        "primary_stressor": "Effort-Reward Imbalance. Feeling invisible despite heavy lifting.",
        "developmental_goal": "Learning to detach self-worth from external productivity.",
    },
    "domain_specific_insight": {
        "topic": "Career",
        "conflict_pattern": "Passive-aggressive compliance. Will say 'yes' to tasks then resent them.",
        "unmet_need": "Recognition of authority without having to ask for it.",
    },
    "therapist_cheat_sheet": {
        "recommended_modality": "ACT (Acceptance and Commitment Therapy) to manage the 'unfixable' current reality.",
        "communication_do": "Validate their exhaustion first. Frame rest as a 'strategic necessity'.",
        "communication_avoid": "Do not suggest 'working harder' or 'manifesting'. They are burned out.",
    },
}


def _llm() -> llm.LLM:
    return google.LLM(model="gemini-2.5-flash")


@pytest.mark.asyncio
async def test_psychologist_greeting():
    """The psychologist agent greets the client warmly."""
    async with (
        _llm() as llm,
        AgentSession(llm=llm, userdata=SessionState()) as session,
    ):
        await session.start(PsychologistAgent(personality_xray=SAMPLE_XRAY))
        result = await session.run(user_input="Hi there")

        await result.expect.next_event(type="message").judge(
            llm,
            intent="""
                Greets the client warmly and shows openness to conversation
                (e.g. asking how they are, inviting them to share, or similar).
                Does NOT mention astrology, charts, birth details, or any astrological concepts.
                Sounds like a psychologist or therapist, not an astrologer.
                """,
        )
        result.expect.no_more_events()


@pytest.mark.asyncio
async def test_no_astrology_terms():
    """The psychologist never uses astrological terminology."""
    async with (
        _llm() as llm,
        AgentSession(llm=llm, userdata=SessionState()) as session,
    ):
        await session.start(PsychologistAgent(personality_xray=SAMPLE_XRAY))
        result = await session.run(
            user_input="I've been feeling really stuck at work lately"
        )

        event = result.expect.next_event(type="message")
        response_text = event.event().item.text_content.lower()

        forbidden_terms = [
            "planet",
            "retrograde",
            "dasha",
            "nakshatra",
            "kundali",
            "chart",
            "zodiac",
            "horoscope",
            "astrology",
        ]
        for term in forbidden_terms:
            assert term not in response_text, (
                f"Forbidden term '{term}' found in response"
            )

        result.expect.no_more_events()


@pytest.mark.asyncio
async def test_therapeutic_response():
    """The psychologist provides clinically sound therapeutic responses."""
    async with (
        _llm() as llm,
        AgentSession(llm=llm, userdata=SessionState()) as session,
    ):
        await session.start(PsychologistAgent(personality_xray=SAMPLE_XRAY))
        result = await session.run(
            user_input="I feel like no matter how hard I work, nobody notices"
        )

        await result.expect.next_event(type="message").judge(
            llm,
            intent="""
                Responds with empathy and validation.
                Does NOT use astrological language.
                Shows understanding of the client's feeling of being unrecognized.
                May offer gentle exploration of the pattern or ask a follow-up question.
                Sounds like a clinical psychologist, not an astrologer or fortune teller.
                """,
        )
