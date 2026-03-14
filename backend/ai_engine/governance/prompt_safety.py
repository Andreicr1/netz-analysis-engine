"""Prompt safety — input sanitisation for user-supplied text before LLM calls.

Provides lightweight defence-in-depth against prompt injection and runaway
input lengths.  This is NOT a silver bullet — it reduces the surface area of
common injection patterns seen in document text that flows into prompts.

Usage::

    from ai_engine.governance.prompt_safety import sanitize_user_input

    safe = sanitize_user_input(raw_document_text)
    result = create_completion(system_prompt=SYSTEM, user_prompt=safe, ...)
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_INJECTION_MARKERS: list[str] = [
    "<|system|>",
    "<|user|>",
    "<|assistant|>",
    "<|im_start|>",
    "<|im_end|>",
    "IGNORE PREVIOUS",
    "IGNORE ALL PREVIOUS",
    "DISREGARD PREVIOUS",
    "FORGET YOUR INSTRUCTIONS",
    "NEW INSTRUCTIONS:",
    "SYSTEM OVERRIDE:",
]

_INJECTION_PATTERN = re.compile(
    r"<\|(?:system|user|assistant|im_start|im_end)\|>",
    re.IGNORECASE,
)


def sanitize_user_input(
    text: str,
    *,
    max_length: int = 200_000,
    strip_injection_markers: bool = True,
) -> str:
    """Sanitise user-supplied text before inserting into an LLM prompt.

    Parameters
    ----------
    text : str
        Raw text (e.g. OCR output, document content, user query).
    max_length : int
        Hard truncation limit in characters.
    strip_injection_markers : bool
        If True, remove known prompt-injection marker strings.

    Returns
    -------
    str — sanitised text, safe to interpolate into a prompt template.

    """
    if not text:
        return ""

    original_len = len(text)
    if original_len > max_length:
        text = text[:max_length]
        logger.debug(
            "sanitize_user_input: truncated %d → %d chars",
            original_len, max_length,
        )

    if strip_injection_markers:
        text_upper = text.upper()
        for marker in _INJECTION_MARKERS:
            if marker.upper() in text_upper:
                text = re.sub(re.escape(marker), "", text, flags=re.IGNORECASE)
                logger.info(
                    "sanitize_user_input: stripped injection marker '%s'",
                    marker,
                )

        text = _INJECTION_PATTERN.sub("", text)

    return text.strip()
