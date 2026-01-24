import logging

logger = logging.getLogger("guardrails")

# Guards are initialized lazily to handle missing validators gracefully
_input_guard = None
_output_guard = None
_guards_initialized = False

# PII entities to detect (excludes DATE_TIME and LOCATION for astrology use case,
# and PERSON to allow personalization with user's name)
SENSITIVE_PII_ENTITIES = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "CRYPTO",
    "IBAN_CODE",
    "IP_ADDRESS",
    "US_SSN",
    "US_PASSPORT",
    "US_DRIVER_LICENSE",
    "US_BANK_NUMBER",
    "US_ITIN",
    "UK_NHS",
    "IN_AADHAAR",
    "IN_PAN",
    "SG_NRIC_FIN",
    "AU_TFN",
    "AU_MEDICARE",
    "MEDICAL_LICENSE",
]


def _init_guards():
    """Initialize guards with validators from Guardrails Hub."""
    global _input_guard, _output_guard, _guards_initialized

    if _guards_initialized:
        return

    _guards_initialized = True

    try:
        from guardrails import Guard, OnFailAction
        from guardrails.hub import DetectPII, ToxicLanguage

        # Input guard - validates user messages
        _input_guard = Guard(name="input-guard").use_many(
            ToxicLanguage(threshold=0.5, on_fail=OnFailAction.EXCEPTION),
            DetectPII(pii_entities=SENSITIVE_PII_ENTITIES, on_fail=OnFailAction.NOOP),
        )

        # Output guard - validates LLM responses
        # PII on FIX to redact any sensitive PII the LLM might accidentally include
        _output_guard = Guard(name="output-guard").use_many(
            ToxicLanguage(threshold=0.5, on_fail=OnFailAction.FIX),
            DetectPII(pii_entities=SENSITIVE_PII_ENTITIES, on_fail=OnFailAction.FIX),
        )

        logger.info("Guardrails initialized successfully")
    except ImportError as e:
        logger.warning(
            f"Guardrails validators not installed: {e}. "
            "Run 'guardrails hub install hub://guardrails/toxic_language' and "
            "'guardrails hub install hub://guardrails/detect_pii' to enable."
        )


def validate_input(text: str) -> tuple[bool, str]:
    """Validate user input. Returns (passed, message)."""
    _init_guards()

    if _input_guard is None:
        # Guardrails not available, pass through
        return True, text

    try:
        result = _input_guard.validate(text)
        if not result.validation_passed:
            logger.warning(f"Input validation failed: {result.validation_summaries}")
            return False, "I can't respond to that kind of message."
        return True, text
    except Exception as e:
        logger.warning(f"Input blocked (toxic content): {e}")
        return False, "I can't respond to that kind of message."


def validate_output(text: str) -> str:
    """Validate and fix LLM output. Returns cleaned text."""
    _init_guards()

    if _output_guard is None:
        # Guardrails not available, pass through
        return text

    try:
        result = _output_guard.validate(text)
        return result.validated_output or text
    except Exception as e:
        logger.error(f"Output validation error: {e}")
        return text
