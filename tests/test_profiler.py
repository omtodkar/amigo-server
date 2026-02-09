import json
from pathlib import Path

import pytest

from profiler import XRAY_REQUIRED_KEYS, AstroProfiler

# Path to sample kundali fixture
SAMPLE_KUNDALI_PATH = Path(__file__).parent.parent / "docs" / "kundali-example.json"

# Astrological terms that must NOT appear in the output values
FORBIDDEN_ASTRO_TERMS = [
    "planet",
    "house",
    "sign",
    "dasha",
    "retrograde",
    "nakshatra",
    "ascendant",
    "kundali",
    "chart",
    "zodiac",
    "horoscope",
    "transit",
    "conjunction",
    "aspect",
    "mahadasha",
    "antardasha",
    "vimshottari",
    "rashi",
    "bhava",
    "lagna",
]

# Zodiac sign names — forbidden in output
FORBIDDEN_SIGN_NAMES = [
    "aries",
    "taurus",
    "gemini",
    "cancer",
    "leo",
    "virgo",
    "libra",
    "scorpio",
    "sagittarius",
    "capricorn",
    "aquarius",
    "pisces",
]

# Planet names — forbidden in astrological context
FORBIDDEN_PLANET_NAMES = [
    "rahu",
    "ketu",
]


@pytest.fixture
def sample_kundali() -> dict:
    with open(SAMPLE_KUNDALI_PATH) as f:
        return json.load(f)


@pytest.fixture
def profiler() -> AstroProfiler:
    return AstroProfiler()


@pytest.mark.asyncio
async def test_xray_structure(profiler: AstroProfiler, sample_kundali: dict) -> None:
    """Verify the X-Ray output contains all required top-level keys."""
    xray = await profiler.generate_xray(sample_kundali)
    assert XRAY_REQUIRED_KEYS.issubset(set(xray.keys())), (
        f"Missing keys: {XRAY_REQUIRED_KEYS - set(xray.keys())}"
    )


@pytest.mark.asyncio
async def test_xray_nested_structure(
    profiler: AstroProfiler, sample_kundali: dict
) -> None:
    """Verify each top-level section contains the expected nested keys."""
    xray = await profiler.generate_xray(sample_kundali)

    expected_nested = {
        "core_identity": {"archetype", "self_esteem_source", "shadow_self"},
        "emotional_architecture": {
            "attachment_style",
            "regulation_strategy",
            "vulnerability_trigger",
        },
        "cognitive_processing": {
            "thinking_style",
            "anxiety_loop_pattern",
            "learning_modality",
        },
        "current_psychological_climate": {
            "season_of_life",
            "primary_stressor",
            "developmental_goal",
            "primary_symptom_match",
            "somatic_signature",
            "risk_factors",
        },
        "domain_specific_insight": {"topic", "conflict_pattern", "unmet_need"},
        "therapist_cheat_sheet": {
            "recommended_modality",
            "communication_do",
            "communication_avoid",
        },
    }

    for section, keys in expected_nested.items():
        assert section in xray, f"Missing section: {section}"
        section_keys = set(xray[section].keys())
        missing = keys - section_keys
        assert not missing, f"Section '{section}' missing keys: {missing}"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="LLM may occasionally leak astrological terms", strict=False)
async def test_no_astrology_term_leakage(
    profiler: AstroProfiler, sample_kundali: dict
) -> None:
    """Verify no astrological terms leak into the output values."""
    xray = await profiler.generate_xray(sample_kundali)
    xray_text = json.dumps(xray).lower()

    for term in FORBIDDEN_ASTRO_TERMS:
        assert term not in xray_text, (
            f"Astrological term '{term}' found in X-Ray output"
        )

    for sign_name in FORBIDDEN_SIGN_NAMES:
        assert sign_name not in xray_text, (
            f"Zodiac sign name '{sign_name}' found in X-Ray output"
        )

    for planet_name in FORBIDDEN_PLANET_NAMES:
        assert planet_name not in xray_text, (
            f"Planet name '{planet_name}' found in X-Ray output"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("topic", ["General", "Career", "Love", "Trauma"])
async def test_focus_topics(
    profiler: AstroProfiler, sample_kundali: dict, topic: str
) -> None:
    """Verify focus_topic is reflected in the domain_specific_insight section."""
    xray = await profiler.generate_xray(sample_kundali, focus_topic=topic)
    assert xray["domain_specific_insight"]["topic"] == topic


@pytest.mark.asyncio
async def test_attachment_style_valid(
    profiler: AstroProfiler, sample_kundali: dict
) -> None:
    """Verify attachment_style is one of the four recognized styles."""
    xray = await profiler.generate_xray(sample_kundali)
    valid_styles = {
        "Secure",
        "Anxious-Preoccupied",
        "Dismissive-Avoidant",
        "Fearful-Avoidant",
    }
    assert xray["emotional_architecture"]["attachment_style"] in valid_styles, (
        f"Invalid attachment style: {xray['emotional_architecture']['attachment_style']}"
    )


@pytest.mark.asyncio
async def test_meta_section(profiler: AstroProfiler, sample_kundali: dict) -> None:
    """Verify meta section contains required fields."""
    xray = await profiler.generate_xray(sample_kundali, focus_topic="Career")
    assert "meta" in xray
    assert xray["meta"]["current_focus_topic"] == "Career"
    assert "generated_at" in xray["meta"]


@pytest.mark.asyncio
async def test_risk_factors_structure(
    profiler: AstroProfiler, sample_kundali: dict
) -> None:
    """Verify risk_factors contains expected sub-fields."""
    xray = await profiler.generate_xray(sample_kundali)
    climate = xray["current_psychological_climate"]
    assert "risk_factors" in climate, (
        "Missing risk_factors in current_psychological_climate"
    )

    risk_factors = climate["risk_factors"]
    assert isinstance(risk_factors, dict), "risk_factors should be a dict"
    assert "addiction_tendency" in risk_factors, "Missing addiction_tendency"
    assert "burnout_tendency" in risk_factors, "Missing burnout_tendency"
    assert "crisis_risk_level" in risk_factors, "Missing crisis_risk_level"


@pytest.mark.asyncio
async def test_crisis_risk_level_valid(
    profiler: AstroProfiler, sample_kundali: dict
) -> None:
    """Verify crisis_risk_level is one of Low, Medium, or High."""
    xray = await profiler.generate_xray(sample_kundali)
    risk_factors = xray["current_psychological_climate"]["risk_factors"]
    valid_levels = {"Low", "Medium", "High"}
    assert risk_factors["crisis_risk_level"] in valid_levels, (
        f"Invalid crisis_risk_level: {risk_factors['crisis_risk_level']}"
    )
