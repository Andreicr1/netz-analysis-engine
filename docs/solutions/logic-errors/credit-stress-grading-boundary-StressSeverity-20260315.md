---
module: StressSeverityService
date: 2026-03-15
problem_type: logic_error
component: service_object
symptoms:
  - "credit_stress score of 10 graded as 'mild' instead of 'moderate'"
  - "Stress severity underreports credit risk when loan delinquency rate >= 2.5%"
  - "Macro stress assessment misleadingly benign during elevated credit conditions"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags: [off-by-one, grading-boundary, stress-severity, credit-stress, quant-engine]
---

# Troubleshooting: Credit Stress Grading Boundary — Score 10 Mapped to "mild" Instead of "moderate"

## Problem

The `credit_stress` sub-dimension in `stress_severity_service.py` had a boundary threshold of 14, which caused a score of 10 to grade as "mild". The credit_stress indicator has only one input (`DRALACBN` — overall loan delinquency rate) worth a maximum of 10 points. When delinquency exceeds 2.5%, the score hits 10 — which should be "moderate" (the maximum meaningful grade for this dimension), not "mild".

## Environment

- Module: `quant_engine/stress_severity_service.py`
- Python: 3.12+
- Affected Component: StressSeverityService sub-dimension grading
- Date: 2026-03-15
- PR: #4 (Credit Engine Quant Architecture Parity)
- Commit: `4d0b5bc`

## Symptoms

- `credit_stress` score of 10 graded as "MILD" instead of "MODERATE"
- Macro stress severity assessment underreports credit risk during elevated delinquency periods
- Overall stress composite score may be misleadingly benign, affecting regime detection and portfolio rebalancing triggers

## What Didn't Work

**Direct solution:** Identified by architecture review agent during PR #4 code review. The boundary value `14` was a default that didn't match the credit_stress indicator's actual scoring range.

## Solution

**Code changes:**

```python
# Before (broken) — stress_severity_service.py:68-73
_DEFAULT_SUBDIM_BOUNDARIES: list[tuple[int, str]] = [
    (0, "none"),
    (14, "mild"),      # <-- BUG: score 10 <= 14, so graded "mild"
    (29, "moderate"),
    (100, "severe"),
]

# After (fixed) — stress_severity_service.py:68-73
_DEFAULT_SUBDIM_BOUNDARIES: list[tuple[int, str]] = [
    (0, "none"),
    (9, "mild"),  # matches original credit_stress: score < 10 = MILD, score >= 10 = MODERATE
    (29, "moderate"),
    (100, "severe"),
]
```

The grading function uses `<=` comparison:

```python
# stress_severity_service.py:185-190
def _grade_score(score: int, boundaries: list[tuple[int, str]]) -> str:
    """Map numeric score to grade label."""
    for threshold, grade in boundaries:
        if score <= threshold:
            return grade
    return boundaries[-1][1] if boundaries else "severe"
```

With threshold `14`: score 10 <= 14 → "mild" (wrong)
With threshold `9`: score 10 > 9, skip → score 10 <= 29 → "moderate" (correct)

**Golden test added:**

```python
# test_market_data_golden.py
def test_credit_stress_score_10_is_moderate(self) -> None:
    """Score of 10 in credit_stress sub-dimension maps to MODERATE."""
    snapshot = {
        "credit_quality": {
            "DRALACBN": {"latest": 3.0},  # >= 2.5 triggers 10 points
        },
        # ... other required fields ...
    }
    result = compute_macro_stress_severity(snapshot)
    assert result["credit_stress"] == "MODERATE"
    assert result["score"] == 10
```

## Why This Works

1. **Root cause:** The `_DEFAULT_SUBDIM_BOUNDARIES` used a generic threshold of 14 for "mild" that didn't account for credit_stress's actual scoring range. The credit_stress dimension has only one indicator (`DRALACBN`) worth max 10 points. With boundary at 14, the maximum possible credit_stress score (10) could never reach "moderate".
2. **The grading logic** iterates thresholds in ascending order, returning the first match where `score <= threshold`. Changing 14 → 9 ensures score 10 falls through to the next tier ("moderate").
3. **Impact:** credit_stress is a sub-dimension of the composite macro stress score. Undergrading it as "mild" instead of "moderate" reduces the overall stress severity assessment, potentially delaying defensive portfolio actions during genuine credit stress periods.

## Prevention

- **Golden tests for every grading boundary:** When a scoring function has discrete output tiers, add a test for each boundary value (not just mid-range values). Test the exact boundary: `score == threshold`, `score == threshold + 1`.
- **Match boundaries to indicator ranges:** When a sub-dimension has a known max score (e.g., credit_stress max = 10), boundaries must be calibrated to that range, not copied from a generic default.
- **Document boundary rationale:** Add inline comments explaining why each threshold value was chosen and what indicator range it corresponds to.

## Related Issues

- See also: [Monolith to Modular Package](../architecture-patterns/monolith-to-modular-package-with-library-migration.md) — lists this bug in the "Bugs Caught During Review" table
- See also: [FRED API Key Case Mismatch](../runtime-errors/fred-api-key-case-mismatch-MarketDataEngine-20260315.md) — fixed in same PR
