# Phase 2: Astro-Profiler Module (Layer B)

## Goal

Build a one-shot LLM translation layer that converts structured kundali JSON into a Personality X-Ray JSON with zero astrological vocabulary. The profiler is the "Hidden Brain" that translates planetary positions into psychological tendencies.

## Dependencies

- **Phase 1** must be complete (provides `fetch_structured_kundali()` and the `kundali_json` field on `SessionState`)

## Files to Create

- `src/profiler.py` — `AstroProfiler` class
- `src/prompts/profiler.md` — Translation prompt for the LLM

## Files to Reference (read-only)

- `docs/kundali.json` — Sample input (structured kundali)
- `docs/personality-x-ray-schema.json` — Output schema
- `docs/personality-x-ray-example.json` — Example output
- `docs/kundali-analysis.md` — Translation dictionary (astrology -> psychology mappings)
- `docs/architecture.md` — Overall architecture description

## Implementation

### 1. Create `src/profiler.py`

```python
"""Astro-Profiler: translates structured kundali JSON into a Personality X-Ray."""

import json
import logging

from livekit.agents import ChatContext
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

    def __init__(self):
        self._llm = google.LLM(model="gemini-2.5-flash")

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
        response = await self._llm.chat(chat_ctx=chat_ctx)
        response_text = response.content

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
            logger.error(f"Failed to parse profiler response as JSON: {e}")
            logger.debug(f"Raw response: {response_text}")
            raise ValueError(f"Profiler returned invalid JSON: {e}") from e

        # Validate required keys exist
        missing_keys = XRAY_REQUIRED_KEYS - set(xray.keys())
        if missing_keys:
            logger.error(f"Profiler output missing keys: {missing_keys}")
            raise ValueError(f"Profiler output missing required keys: {missing_keys}")

        return xray
```

**Important implementation notes:**

- Use `self._llm.chat()` with a `ChatContext`. Check the LiveKit Agents SDK docs for the exact `chat()` API — it may return a `ChatCompletion` object where you access `.content` or similar. Consult the LiveKit docs MCP server if the exact return type is unclear.
- The JSON parsing must handle markdown code fences since LLMs often wrap JSON in ` ```json ... ``` ` blocks.
- Validation is intentionally minimal (just checking top-level keys exist). The LLM prompt does the heavy lifting.

### 2. Create `src/prompts/profiler.md`

This is the most critical file. It must contain:

1. **Role definition**: "You are a clinical psychology translator"
2. **Input specification**: Raw kundali JSON with planetary positions, dasha periods, ascendant report
3. **Translation dictionary**: Embed the core mapping framework from `docs/kundali-analysis.md`. Key mappings include:

   **Planets to Psychological Archetypes:**
   - Sun -> Ego, identity, authority needs, self-esteem source
   - Moon -> Emotional processing, attachment style, vulnerability triggers
   - Mars -> Anger expression, assertiveness, conflict patterns
   - Mercury -> Thinking style, anxiety loops, communication patterns
   - Jupiter -> Optimism/pessimism, meaning-making, growth orientation
   - Venus -> Love language, relationship needs, aesthetic values
   - Saturn -> Discipline patterns, fear/avoidance, long-term coping
   - Rahu -> Obsessive tendencies, unconventional desires, restlessness
   - Ketu -> Detachment patterns, spiritual tendencies, loss processing

   **Houses to Life Domains:**
   - 1st house -> Self-image, default persona
   - 4th house -> Emotional foundation, home/security needs
   - 5th house -> Creativity, self-expression, romantic patterns
   - 7th house -> Partnership dynamics, projection patterns
   - 8th house -> Crisis response, transformation capacity
   - 10th house -> Career identity, public persona, authority relationship
   - 12th house -> Unconscious patterns, isolation needs

   **Dasha to Temporal Psychology:**
   - Current Mahadasha planet -> "Season of life" (e.g., Saturn Dasha = "Wintering/Restructuring")
   - Current Antardasha -> Fine-tuning of the season
   - Deeper dasha levels -> Micro-phase psychological emphasis

4. **Output format**: JSON strictly following `docs/personality-x-ray-schema.json`
5. **Focus topic handling**: The `focus_topic` parameter changes the `domain_specific_insight` section:
   - "General" -> Broad personality overview
   - "Career" -> Work patterns, authority dynamics, professional stress
   - "Love" -> Attachment style emphasis, relationship conflict patterns
   - "Trauma" -> Defense mechanisms, crisis response, healing capacity
6. **HARD RULE**: Zero astrological terms in output. Forbidden words: "planet", "house", "sign", "dasha", "retrograde", "nakshatra", "ascendant", "kundali", "chart", "birth chart", "zodiac", "horoscope", "Rahu", "Ketu", "Mahadasha", "Antardasha", any zodiac sign names used in astrological context

Here is the prompt template:

```markdown
# Clinical Psychology Translator

You are a clinical psychology translator. Your job is to convert raw astrological chart data into a pure psychological profile. You are an expert in both Vedic astrology interpretation and modern clinical psychology (CBT, IFS, Attachment Theory).

## Your Task

Given a structured chart data JSON and a focus topic, produce a Personality X-Ray JSON that:
1. Captures the person's psychological tendencies, attachment patterns, cognitive style, and current life phase
2. Contains ZERO astrological vocabulary
3. Is directly useful for a therapist who knows nothing about astrology

## Translation Framework

Use these mappings to convert chart data into psychology:

### Core Identity (from Sun, Ascendant, 1st House Lord)
- The Sun's sign and house reveal the ego structure and self-esteem source
- The Ascendant sign reveals the default persona and first impression
- The 1st house lord's placement reveals where identity issues manifest
- Combine these into: archetype, self_esteem_source, shadow_self

### Emotional Architecture (from Moon, 4th House)
- Moon sign determines emotional processing style:
  - Fire signs (Aries/Leo/Sagittarius): Reactive, expressive, quickly processed
  - Earth signs (Taurus/Virgo/Capricorn): Suppressed, achievement-linked, slow-burning
  - Air signs (Gemini/Libra/Aquarius): Intellectualized, detached, socially mediated
  - Water signs (Cancer/Scorpio/Pisces): Deep, absorptive, boundary-blurred
- Moon's house shows WHERE emotional needs manifest
- Afflictions to Moon (malefic aspects/conjunctions) -> attachment insecurity
- Map to: attachment_style, regulation_strategy, vulnerability_trigger

### Cognitive Processing (from Mercury, 3rd/5th Houses)
- Mercury's sign -> thinking style (fast/slow, intuitive/analytical)
- Mercury retrograde -> tendency to replay/ruminate
- Mercury's house -> domain of cognitive focus
- 3rd house -> communication style; 5th house -> creative expression
- Map to: thinking_style, anxiety_loop_pattern, learning_modality

### Current Psychological Climate (from Dasha periods)
- Major dasha planet determines the "season of life":
  - Sun period: Identity crisis or empowerment
  - Moon period: Emotional sensitivity heightened
  - Mars period: Conflict, energy, impatience
  - Mercury period: Learning, communication, anxiety
  - Jupiter period: Expansion, optimism, overcommitment
  - Venus period: Relationships, pleasure-seeking, comfort
  - Saturn period: Restriction, discipline, isolation/burnout
  - Rahu period: Obsession, unconventional paths, restlessness
  - Ketu period: Loss, detachment, spiritual seeking
- Sub-periods fine-tune the season
- Map to: season_of_life, primary_stressor, developmental_goal

### Domain-Specific Insight (based on focus_topic)
- Career: Analyze 10th house, Saturn, Sun, 6th house patterns
- Love: Analyze 7th house, Venus, Moon, 5th house patterns
- Trauma: Analyze 8th house, 12th house, Moon afflictions, Saturn/Ketu patterns
- General: Provide the most pressing insight based on current dasha

### Therapist Cheat Sheet
- Based on the overall profile, recommend:
  - Best therapeutic modality (CBT, IFS, ACT, Somatic, DBT)
  - Communication approach that works for this personality
  - Communication approach to avoid

## Output Format

Return a single JSON object with this exact structure:

```json
{
  "meta": {
    "generated_at": "<ISO-8601 timestamp>",
    "current_focus_topic": "<the focus topic provided>"
  },
  "core_identity": {
    "archetype": "<persona label, e.g., 'The Reluctant King'>",
    "self_esteem_source": "<what drives their ego>",
    "shadow_self": "<unconscious defense pattern>"
  },
  "emotional_architecture": {
    "attachment_style": "<Secure|Anxious-Preoccupied|Dismissive-Avoidant|Fearful-Avoidant>",
    "regulation_strategy": "<how they self-soothe>",
    "vulnerability_trigger": "<what makes them feel unsafe>"
  },
  "cognitive_processing": {
    "thinking_style": "<e.g., 'Hyper-Analytical loop'>",
    "anxiety_loop_pattern": "<specific worry shape>",
    "learning_modality": "<Visual|Auditory|Kinesthetic|Logical>"
  },
  "current_psychological_climate": {
    "season_of_life": "<metaphorical phase>",
    "primary_stressor": "<root cause of current pressure>",
    "developmental_goal": "<skill life is forcing them to learn>"
  },
  "domain_specific_insight": {
    "topic": "<the focus topic>",
    "conflict_pattern": "<how they handle conflict in this domain>",
    "unmet_need": "<what they need but don't have>"
  },
  "therapist_cheat_sheet": {
    "recommended_modality": "<therapeutic approach>",
    "communication_do": "<what works>",
    "communication_avoid": "<what to avoid>"
  }
}
```

## ABSOLUTE RULES

1. Your output must be valid JSON only. No text before or after the JSON.
2. NEVER use any astrological terms in your output. Forbidden words include: planet, house, sign, chart, birth chart, kundali, dasha, retrograde, nakshatra, ascendant, zodiac, horoscope, transit, conjunction, aspect, and any zodiac sign names (Aries, Taurus, etc.) or planet names (Sun, Moon, Mars, etc.) when used in astrological context.
3. Write as a clinical psychologist would — use psychology terminology (attachment theory, cognitive distortions, defense mechanisms, etc.)
4. Be specific and actionable, not vague. "Dismissive-Avoidant attachment" is better than "has relationship issues."
5. The therapist_cheat_sheet should contain direct, practical instructions.
```

**Note:** The above is a starting template. Refine the prompt based on testing. The translation framework section should be expanded with more specific mappings from `docs/kundali-analysis.md` as needed.

### 3. Schema Reference Files

These files already exist in `docs/` and should be read but not modified:

- `docs/personality-x-ray-schema.json` — Defines the output structure with field descriptions
- `docs/personality-x-ray-example.json` — Shows a concrete example for "Career_Burnout" focus
- `docs/kundali-analysis.md` — Contains the full analysis framework for mapping astrology to life domains

## Testing

Create `tests/test_profiler.py`:

1. **Test output structure**: Call `generate_xray()` with the sample kundali from `docs/kundali.json`. Verify the output has all 6 required top-level keys.

2. **Test astrology term leakage**: Grep the output JSON string for forbidden astrological terms. The following words should NOT appear in the output values (they may appear in keys like `attachment_style`):
   - `planet`, `house`, `sign`, `dasha`, `retrograde`, `nakshatra`, `ascendant`, `kundali`, `chart`, `zodiac`, `horoscope`
   - Zodiac sign names when used in astrological context: `Aries`, `Taurus`, `Gemini`, `Cancer`, `Leo`, `Virgo`, `Libra`, `Scorpio`, `Sagittarius`, `Capricorn`, `Aquarius`, `Pisces`

3. **Test focus topics**: Call `generate_xray()` with different `focus_topic` values ("General", "Career", "Love", "Trauma") and verify the `domain_specific_insight.topic` field matches.

4. **Test invalid JSON handling**: Mock the LLM to return non-JSON text and verify `ValueError` is raised.

```python
import json
import pytest
from profiler import AstroProfiler

# Load sample kundali for testing
SAMPLE_KUNDALI_PATH = "docs/kundali.json"

@pytest.fixture
def sample_kundali():
    with open(SAMPLE_KUNDALI_PATH) as f:
        return json.load(f)

@pytest.fixture
def profiler():
    return AstroProfiler()

FORBIDDEN_ASTRO_TERMS = [
    "planet", "house", "sign", "dasha", "retrograde", "nakshatra",
    "ascendant", "kundali", "chart", "zodiac", "horoscope",
]

@pytest.mark.asyncio
async def test_xray_structure(profiler, sample_kundali):
    xray = await profiler.generate_xray(sample_kundali)
    required_keys = {
        "core_identity", "emotional_architecture", "cognitive_processing",
        "current_psychological_climate", "domain_specific_insight",
        "therapist_cheat_sheet",
    }
    assert required_keys.issubset(set(xray.keys()))

@pytest.mark.asyncio
async def test_no_astrology_leakage(profiler, sample_kundali):
    xray = await profiler.generate_xray(sample_kundali)
    xray_text = json.dumps(xray).lower()
    for term in FORBIDDEN_ASTRO_TERMS:
        assert term not in xray_text, f"Astrology term '{term}' found in X-Ray output"

@pytest.mark.asyncio
@pytest.mark.parametrize("topic", ["General", "Career", "Love", "Trauma"])
async def test_focus_topics(profiler, sample_kundali, topic):
    xray = await profiler.generate_xray(sample_kundali, focus_topic=topic)
    assert xray["domain_specific_insight"]["topic"] == topic
```

**Note:** These tests make real LLM calls. They require `GOOGLE_API_KEY` to be set. Mark them appropriately if you need to skip in CI.

## Verification

```bash
uv run pytest tests/test_profiler.py -v
uv run ruff format src/profiler.py
uv run ruff check src/profiler.py
```
