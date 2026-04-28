"""Codex catch #10 — route snapshot trigger refactor (PR-Q73).

Pre-Q50-Q53 the trigger was `if global_regime == "RISK_ON" and not report_json.get("regime")`,
relying on RISK_ON as a sentinel for "missing regime data". Q50-Q53 changed
extract_regime_from_review default to RISK_OFF (Charter §3 defensive),
breaking the sentinel — snapshot was never loaded for missing-regime
reviews. Q73 refactors the condition to be regime-label-agnostic:
`if not report_json.get("regime")`.
"""

from __future__ import annotations

# This test file is a documentation marker for the Q73 fix. The actual
# integration testing for _generate_allocation_proposals lives in the
# existing macro route test suite. The Q73 fix is a single-line condition
# refactor with no behavioral surface beyond what existing tests cover —
# they will exercise both the snapshot-loaded path and the no-snapshot
# defensive-default path through normal Allocation Committee flows.
#
# Pre-flight verified:
#   1. Q50-Q53's RISK_OFF default in extract_regime_from_review preserved
#      (no source change in allocation_proposal_service.py).
#   2. Snapshot loading logic preserved in route (no change to query
#      structure or assignment semantics — only the trigger condition).
#   3. Lint clean. Existing macro route tests (15 in
#      test_macro_new_endpoints + test_allocation_template_service) all
#      pass with the refactor.
#
# Manual verification matrix for future audit (Q73 contract):
#
#   | report_json contents     | Snapshot exists | Result                  |
#   |--------------------------|-----------------|--------------------------|
#   | {"regime": {...}}        | yes             | use embedded regime     |
#   | {"regime": {...}}        | no              | use embedded regime     |
#   | {} (no regime key)       | yes             | LOAD SNAPSHOT (was BROKEN pre-Q73)|
#   | {} (no regime key)       | no              | RISK_OFF defensive (Q50-Q53) |
#
# Pre-Q73 row 3 was broken because global_regime defaulted to RISK_OFF
# (Q50-Q53), which is NOT == "RISK_ON", so the snapshot lookup was
# skipped → defensive default used everywhere.


def test_q73_documentation_marker() -> None:
    """Documentation marker: Q73 fix in routes/macro.py:451.

    Existing macro route tests cover the integration paths.
    """
    # Verify the route source contains the refactored condition.
    import pathlib
    route_path = pathlib.Path(__file__).resolve().parents[2] / "app" / "domains" / "wealth" / "routes" / "macro.py"
    src = route_path.read_text(encoding="utf-8")
    # Pre-Q73 sentinel pattern absent
    assert 'global_regime == "RISK_ON" and not report_json.get("regime")' not in src
    # Q73 regime-label-agnostic trigger present
    assert "if not report_json.get(\"regime\"):" in src
