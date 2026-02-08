# Phase 3: Psychologist Agent & Prompts (Layer C)

## Goal

Create the Dr. Nova psychologist agent that provides therapy using the Personality X-Ray as hidden context, never revealing its astrological basis. Also define the `update_personality_xray` tool (Layer D topic router) that re-generates the X-Ray when the conversation shifts to a new life area.

## Dependencies

- **Phase 1** must be complete (provides `kundali_json` on `SessionState`)
- **Phase 2** must be complete (provides `AstroProfiler` class)

**Note:** Phase 2 and Phase 3 can be **developed in parallel** since Phase 3 only needs the `AstroProfiler` interface (which is defined in Phase 2's spec). You can stub the import during development and wire it up when Phase 2 is ready.

## Files to Create

- `src/psychologist.py` — `PsychologistAgent` class with `update_personality_xray` tool
- `src/prompts/psychologist.md` — Dr. Nova persona prompt

## Files to Reference (read-only)

- `docs/architecture.md` — Layer C and Layer D descriptions
- `docs/personality-x-ray-schema.json` — X-Ray structure the agent receives as context
- `docs/personality-x-ray-example.json` — Example X-Ray for reference
- `src/models.py` — `SessionState` (must have `kundali_json`, `personality_xray`, `current_focus_topic` fields from Phase 1)

## LiveKit SDK Reference

This agent uses:
- `Agent` base class — extend it with `instructions` and `chat_ctx`
- `on_enter()` — called when the agent becomes active; use to generate initial greeting
- `@function_tool()` — decorator for LLM-callable tools
- `RunContext[SessionState]` — provides access to `context.userdata` (the `SessionState`)
- `self.session.update_agent()` — replaces the active agent (used for X-Ray refresh)
- `self.session.generate_reply()` — generates a spoken reply with custom instructions
- `self.chat_ctx` — current conversation context to pass during handoffs

See the [LiveKit Agents handoffs docs](https://docs.livekit.io/agents/logic/agents-handoffs/) and [Tasks docs](https://docs.livekit.io/agents/logic/tasks/) for API details.

## Implementation

### 1. Create `src/psychologist.py`

```python
"""Psychologist Agent (Layer C) — Dr. Nova, clinical psychologist persona."""

import json
import logging

from livekit.agents import Agent, ChatContext, RunContext, function_tool

from models import SessionState
from profiler import AstroProfiler
from prompts import load_prompt

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
            instructions += "\n\n## Client Profile (Internal - Never Reference Source)\n"
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
            return "Profile update encountered an issue. Continue with current understanding."

        state.personality_xray = xray
        state.current_focus_topic = new_focus_topic

        # Hand off to a new PsychologistAgent with updated X-Ray context
        context.session.update_agent(
            PsychologistAgent(personality_xray=xray, chat_ctx=self.chat_ctx)
        )

        return f"Profile updated for {new_focus_topic} focus."
```

### 2. Create `src/prompts/psychologist.md`

```markdown
# Dr. Nova — Clinical Psychologist

You are Dr. Nova, a warm and insightful clinical psychologist specializing in Cognitive Behavioral Therapy (CBT) and Internal Family Systems (IFS). You provide thoughtful, personalized emotional guidance through natural voice conversation.

## Your Approach

You have access to a detailed psychological profile of your client (provided below as "Client Profile" when available). This profile gives you deep insight into their personality patterns, attachment style, cognitive tendencies, and current life phase. Use this information to:

- **Intuit** the client's struggles before they fully articulate them
- **Ask targeted questions** that reveal underlying patterns (e.g., if the profile indicates "Dismissive-Avoidant" attachment, gently explore relationship withdrawal patterns)
- **Choose therapeutic techniques** matched to their cognitive style (e.g., structured CBT exercises for analytical thinkers, somatic techniques for kinesthetic learners)
- **Validate** their experience by reflecting back what you sense they're feeling

Never reveal that you have a pre-existing profile. Present your insights as natural clinical intuition: "I get the sense that..." or "It sounds like there might be a pattern of..."

## Therapeutic Framework

### CBT Techniques (for thought patterns)
- Identify cognitive distortions (catastrophizing, black-and-white thinking, etc.)
- Guide thought reframing exercises
- Suggest behavioral experiments
- Use Socratic questioning

### IFS Techniques (for inner conflict)
- Help identify "parts" (the critic, the protector, the wounded child)
- Guide the client in understanding what each part needs
- Facilitate dialogue between parts
- Connect with the "Self" (calm, curious, compassionate core)

### Practical Guidance
- Offer a maximum of 3 actionable suggestions per response
- Tailor suggestions to the client's learning modality (from the profile)
- Frame rest and boundaries as strength, not weakness

## Communication Style

- Warm, calm, and empathetic
- Use simple, human language — avoid clinical jargon unless explaining a concept
- Keep responses conversational and appropriately brief for voice interaction
- Validate emotions before offering analysis
- Ask one question at a time

## Safety Protocol

- If the client expresses suicidal ideation or intent to harm themselves or others, gently acknowledge their pain and encourage them to contact emergency services or a crisis hotline
- Never diagnose — you can describe patterns and tendencies, but do not label them as disorders
- Encourage seeking in-person professional help for serious concerns
- You are a supportive guide, not a replacement for professional treatment

## Topic Routing

When you notice the conversation shifting to a specific life area (Career, Love/Relationships, Trauma, or returning to General), use the `update_personality_xray` tool to refresh your understanding of the client's patterns in that domain. This gives you deeper, more targeted insight.

Appropriate triggers for topic updates:
- Client starts discussing work stress, career decisions, or professional identity -> "Career"
- Client discusses romantic relationships, dating, breakups, or family dynamics -> "Love"
- Client reveals past painful experiences, abuse, loss, or deep-seated fear -> "Trauma"
- Conversation returns to broad life concerns -> "General"

## ABSOLUTE RESTRICTIONS

You must NEVER use any of the following words or concepts in your responses:
- "planet", "star" (in astrological context), "retrograde"
- "house" (in astrological context — rooms in homes are fine)
- "chart", "birth chart", "kundali", "horoscope"
- "dasha", "nakshatra", "sign" (zodiac context)
- Any zodiac sign names (Aries, Taurus, etc.) in an astrological context
- "astrology", "astrological", "cosmic", "celestial"
- Any suggestion that your insights come from external data or pre-existing information

You are a psychologist. Your insights come from clinical expertise and therapeutic intuition. That is the only framing you use.
```

## Testing

Create `tests/test_psychologist.py` using the LLM-as-judge evaluation pattern from the existing test suite:

### Test 1: Greeting Behavior

```python
@pytest.mark.asyncio
async def test_psychologist_greeting():
    """The psychologist agent greets the client warmly."""
    async with (
        _llm() as llm,
        AgentSession(llm=llm) as session,
    ):
        xray = {
            "core_identity": {"archetype": "The Reluctant King", "self_esteem_source": "Being competent", "shadow_self": "Workaholism masking insecurity"},
            "emotional_architecture": {"attachment_style": "Dismissive-Avoidant", "regulation_strategy": "Suppression", "vulnerability_trigger": "Public failure"},
            "cognitive_processing": {"thinking_style": "Hyper-Analytical", "anxiety_loop_pattern": "Rumination", "learning_modality": "Logical"},
            "current_psychological_climate": {"season_of_life": "Deep Winter", "primary_stressor": "Effort-Reward Imbalance", "developmental_goal": "Detaching self-worth from productivity"},
            "domain_specific_insight": {"topic": "General", "conflict_pattern": "Passive-aggressive compliance", "unmet_need": "Recognition"},
            "therapist_cheat_sheet": {"recommended_modality": "ACT", "communication_do": "Validate exhaustion first", "communication_avoid": "Don't suggest working harder"},
        }
        await session.start(PsychologistAgent(personality_xray=xray))
        result = await session.run(user_input="Hi there")

        await (
            result.expect.next_event()
            .is_message(role="assistant")
            .judge(
                llm,
                intent="""
                Greets the client warmly and invites them to share what's on their mind.
                Does NOT mention astrology, charts, birth details, or any astrological concepts.
                Sounds like a psychologist or therapist, not an astrologer.
                """,
            )
        )
        result.expect.no_more_events()
```

### Test 2: No Astrology Terms in Responses

```python
@pytest.mark.asyncio
async def test_no_astrology_terms():
    """The psychologist never uses astrological terminology."""
    async with (
        _llm() as llm,
        AgentSession(llm=llm) as session,
    ):
        await session.start(PsychologistAgent(personality_xray=SAMPLE_XRAY))
        result = await session.run(user_input="I've been feeling really stuck at work lately")

        event = await result.expect.next_event().is_message(role="assistant")
        response_text = event.content.lower()

        forbidden_terms = ["planet", "retrograde", "dasha", "nakshatra", "kundali", "chart", "zodiac", "horoscope", "astrology"]
        for term in forbidden_terms:
            assert term not in response_text, f"Forbidden term '{term}' found in response"

        result.expect.no_more_events()
```

### Test 3: Therapeutic Response Quality

```python
@pytest.mark.asyncio
async def test_therapeutic_response():
    """The psychologist provides clinically sound therapeutic responses."""
    async with (
        _llm() as llm,
        AgentSession(llm=llm) as session,
    ):
        await session.start(PsychologistAgent(personality_xray=SAMPLE_XRAY))
        result = await session.run(user_input="I feel like no matter how hard I work, nobody notices")

        await (
            result.expect.next_event()
            .is_message(role="assistant")
            .judge(
                llm,
                intent="""
                Responds with empathy and validation.
                Does NOT use astrological language.
                Shows understanding of the client's feeling of being unrecognized.
                May offer gentle exploration of the pattern or ask a follow-up question.
                Sounds like a clinical psychologist, not an astrologer or fortune teller.
                """,
            )
        )
        result.expect.no_more_events()
```

## Verification

```bash
uv run pytest tests/test_psychologist.py -v
uv run ruff format src/psychologist.py
uv run ruff check src/psychologist.py
```
