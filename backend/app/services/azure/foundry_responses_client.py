from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from app.core.config import settings


@dataclass(frozen=True)
class FoundryHealth:
    ok: bool
    detail: str | None = None


@dataclass(frozen=True)
class FoundryResult:
    output_text: str
    model: str
    raw: Any


def get_foundry_client() -> OpenAI:
    """Return an ``OpenAI`` client using the direct OpenAI API key.

    The client talks to ``https://api.openai.com/v1`` (default).
    """
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise ValueError("OPENAI_API_KEY not configured")
    return OpenAI(api_key=api_key)


class FoundryResponsesClient:
    def __init__(self) -> None:
        if not settings.OPENAI_MODEL_INTELLIGENCE:
            raise ValueError("OPENAI_MODEL_INTELLIGENCE not configured")
        self._client = get_foundry_client()

    def generate_answer(self, *, system_prompt: str, user_prompt: str) -> FoundryResult:
        model = settings.OPENAI_MODEL_INTELLIGENCE
        resp = self._client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return FoundryResult(output_text=resp.output_text, model=model, raw=resp)


def safe_parse_json_object(text: str) -> dict[str, Any]:
    """Robustly parse a JSON object from model output (Responses API output_text).
    """
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    return json.loads(t)


def health_check_foundry() -> FoundryHealth:
    try:
        c = FoundryResponsesClient()
        _ = c.generate_answer(system_prompt="Return JSON: {\"answer\":\"ok\",\"citations\":[{\"chunk_id\":\"x\",\"rationale\":\"y\"}]}", user_prompt="Ping")
        return FoundryHealth(ok=True)
    except Exception as e:
        msg = str(e) or repr(e)
        return FoundryHealth(ok=False, detail=f"{type(e).__name__}: {msg}")

