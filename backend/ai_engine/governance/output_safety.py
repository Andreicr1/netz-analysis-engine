"""LLM output sanitization before database persistence.

Mirrors prompt_safety.py (input sanitization) — this handles OUTPUT sanitization.
Cross-vertical: used by deep_review, memo, domain_ai, and future verticals.

Usage::

    from ai_engine.governance.output_safety import sanitize_llm_text

    profile.summary_ic_ready = sanitize_llm_text(analysis.get("executiveSummary"))
    profile.sector_focus = sanitize_llm_text(val, strip_all_html=True, max_length=160)
"""

from __future__ import annotations

import re
import unicodedata

import nh3
import structlog

from ai_engine.governance._constants import INJECTION_MARKERS

logger = structlog.get_logger()

# Tags safe in Markdown-rendered content (financial notation needs <sup>, tables need <table>)
_SAFE_TAGS: set[str] = {
    "b", "i", "em", "strong", "code", "mark", "s", "del", "ins",
    "sup", "sub", "br",
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "blockquote", "pre",
    "table", "thead", "tbody", "tr", "th", "td",
    "a", "abbr", "hr",
}
_SAFE_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "title"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}

_WHITESPACE_COLLAPSE = re.compile(r"\n{3,}")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_MAX_LLM_TEXT_LENGTH = 100_000  # 100KB sanity cap


def sanitize_llm_text(
    text: str | None,
    *,
    max_length: int | None = None,
    strip_all_html: bool = False,
) -> str | None:
    """Sanitize LLM output for safe DB persistence.

    Uses nh3 (Rust-based, DOM-aware) — NOT regex. Handles unclosed tags,
    attribute injection, entity encoding attacks that regex misses.

    Default: allowlist safe Markdown-compatible tags (preserves <sup>, <table>, etc.).
    strip_all_html=True: remove ALL tags (for VARCHAR fields where Markdown won't render).
    """
    if text is None:
        return None
    if not isinstance(text, str):
        logger.warning("sanitize_llm_text_non_string", text_type=type(text).__name__)
        return text  # type: ignore[return-value]
    if not text:
        return text
    # 1. Unicode NFC normalization (canonical, non-lossy — NOT NFKC which destroys
    #    financial notation like superscripts and ligatures)
    text = unicodedata.normalize("NFC", text)
    # 2. Strip control characters (keep \t, \n, \r)
    text = _CONTROL_CHARS.sub("", text)
    # 3. HTML sanitization via nh3 (DOM-based, handles entity attacks internally)
    #    Do NOT call html.unescape() — nh3 handles entities correctly.
    #    unescape() before nh3 converts &lt;script&gt; → <script> = vulnerability.
    if strip_all_html:
        text = nh3.clean(text, tags=set())
    else:
        text = nh3.clean(text, tags=_SAFE_TAGS, attributes=_SAFE_ATTRIBUTES)
    # 4. Strip prompt injection markers (defense-in-depth against stored indirect injection)
    text_upper = text.upper()
    for marker in INJECTION_MARKERS:
        if marker.upper() in text_upper:
            text = re.sub(re.escape(marker), "", text, flags=re.IGNORECASE)
            logger.warning("stripped_injection_marker", marker=marker)
            # Recompute upper after modification
            text_upper = text.upper()
    # 5. Collapse excessive blank lines
    text = _WHITESPACE_COLLAPSE.sub("\n\n", text.strip())
    # 6. Length enforcement
    effective_max = max_length if max_length is not None else _MAX_LLM_TEXT_LENGTH
    if len(text) > effective_max:
        text = text[:effective_max]
    return text
