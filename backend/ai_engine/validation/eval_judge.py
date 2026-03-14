from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ai_engine.model_config import get_model
from ai_engine.validation.validation_schema import LayerScore, MetricResult, MetricStatus

JudgeCall = Callable[[str, str], dict[str, Any]]


def evaluate_llm_judge(
    *,
    chapter_tag: str,
    chapter_title: str,
    chapter_text: str,
    memo_context: dict[str, Any],
    judge_call: JudgeCall | None = None,
) -> LayerScore:
    if not chapter_text.strip():
        return LayerScore(
            layer="layer4",
            applicable=True,
            status=MetricStatus.DATA_ISSUE,
            score=0.0,
            metrics=[
                MetricResult(
                    metric="chapter_coherence",
                    status=MetricStatus.DATA_ISSUE,
                    score=0.0,
                    reason="Chapter text is empty.",
                )
            ],
            warnings=["Layer 4 skipped because chapter text is empty."],
        )

    payload = _build_payload(
        chapter_tag=chapter_tag,
        chapter_title=chapter_title,
        chapter_text=chapter_text,
        memo_context=memo_context,
    )
    system_prompt = _load_system_prompt()

    if judge_call is None:
        from ai_engine.openai_client import create_completion

        result = create_completion(
            system_prompt=system_prompt,
            user_prompt=payload,
            model=get_model("eval_judge"),
            temperature=0.1,
            max_tokens=600,
            response_format={"type": "json_object"},
            stage="eval_judge",
        )
        parsed = json.loads(result.text)
    else:
        parsed = judge_call(system_prompt, payload)

    metrics = [
        _metric_from_judge(parsed, "chapter_coherence"),
        _metric_from_judge(parsed, "cross_chapter_consistency"),
        _metric_from_judge(parsed, "synthesis_completeness"),
        _metric_from_judge(parsed, "tone_professional"),
    ]
    applicable_scores = [metric.score for metric in metrics]
    overall = round(sum(applicable_scores) / len(applicable_scores), 4) if applicable_scores else 0.0
    status = MetricStatus.FAIL if any(metric.status == MetricStatus.FAIL for metric in metrics) else MetricStatus.WARN if any(metric.status == MetricStatus.WARN for metric in metrics) else MetricStatus.PASS

    return LayerScore(
        layer="layer4",
        applicable=True,
        status=status,
        score=overall,
        metrics=metrics,
        warnings=list(parsed.get("flags", []) or []),
        blocking=False,
    )


def _build_payload(
    *,
    chapter_tag: str,
    chapter_title: str,
    chapter_text: str,
    memo_context: dict[str, Any],
) -> str:
    context_payload = {
        "chapter_tag": chapter_tag,
        "chapter_title": chapter_title,
        "chapter_text": chapter_text,
        "decision_anchor": memo_context.get("decision_anchor", {}),
        "critic_output": memo_context.get("critic_output", {}),
        "policy_compliance": memo_context.get("policy_compliance", {}),
        "quant_summary": memo_context.get("quant_summary", {}),
        "chapter_summaries": memo_context.get("chapter_summaries", {}),
        "chapter_count_found": memo_context.get("chapter_count_found", 0),
        "chapter_count_expected": memo_context.get("chapter_count_expected", 14),
    }
    return json.dumps(context_payload, indent=2, default=str)


def _metric_from_judge(parsed: dict[str, Any], key: str) -> MetricResult:
    raw = parsed.get(key, {}) or {}
    score = raw.get("score", 0.0)
    if not isinstance(score, (int, float)):
        score = 0.0
    score = max(0.0, min(1.0, float(score)))
    status = MetricStatus.PASS if score >= 0.8 else MetricStatus.WARN if score >= 0.6 else MetricStatus.FAIL
    return MetricResult(
        metric=key,
        status=status,
        score=score,
        reason=str(raw.get("reason", "")),
    )


def _load_system_prompt() -> str:
    template_path = Path(__file__).resolve().parents[1] / "prompts" / "intelligence" / "eval_judge.j2"
    text = template_path.read_text(encoding="utf-8")
    text = re.sub(r"\{#-.*?-#\}\s*", "", text, flags=re.DOTALL)
    text = text.replace("{% raw %}", "").replace("{% endraw %}", "")
    return text.strip()
