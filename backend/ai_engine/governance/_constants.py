"""Shared constants for input/output safety modules.

Single source of truth for injection markers used by both prompt_safety.py
(input sanitization) and output_safety.py (output sanitization).
"""

from __future__ import annotations

INJECTION_MARKERS: list[str] = [
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
