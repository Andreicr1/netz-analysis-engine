"""Shared protocols for wealth vertical engines.

CallOpenAiFn lives here (not in dd_report/) so that sibling packages
like critic/ can import it without creating dd_report → critic
or critic → dd_report circular dependencies.
"""

from __future__ import annotations

from typing import Any, Protocol


class CallOpenAiFn(Protocol):
    """Structural type for an LLM call function.

    The caller provides a callable matching this signature.
    The callable handles model selection, retries, and credentials.
    """

    def __call__(
        self,
        system_prompt: str,
        user_content: str,
        *,
        max_tokens: int = 4000,
        model: str | None = None,
    ) -> dict[str, Any]: ...
