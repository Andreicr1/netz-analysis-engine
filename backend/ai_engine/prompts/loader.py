"""Prompt loader — reads .txt prompt templates from the prompts/ directory tree.

Directory layout::

    ai_engine/prompts/
    ├── loader.py              # this file
    ├── classification/
    │   ├── system.txt
    │   └── user.txt
    ├── extraction/
    │   ├── system.txt
    │   └── user.txt
    └── ...

Templates use Python ``str.format()`` placeholders::

    Classify the following document:
    Title: {title}
    Content: {content}

Usage::

    from ai_engine.prompts.loader import load_prompt

    prompt = load_prompt("classification", "system", doc_types="...")
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=128)
def _read_template(category: str, name: str) -> str | None:
    """Read a prompt template file, returning None if not found."""
    path = _PROMPTS_DIR / category / f"{name}.txt"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def load_prompt(category: str, name: str, **kwargs: str) -> str:
    """Load and format a prompt template.

    Parameters
    ----------
    category : str
        Subdirectory name (e.g. "classification", "extraction").
    name : str
        Template name without extension (e.g. "system", "user").
    **kwargs : str
        Format variables to substitute into the template.

    Returns
    -------
    str — the formatted prompt.

    Raises
    ------
    FileNotFoundError
        If the template file does not exist.

    """
    template = _read_template(category, name)
    if template is None:
        raise FileNotFoundError(
            f"Prompt template not found: {category}/{name}.txt "
            f"(looked in {_PROMPTS_DIR / category})",
        )

    if kwargs:
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.error(
                "Missing placeholder in prompt %s/%s: %s", category, name, e,
            )
            raise

    return template
