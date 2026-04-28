# Backlog: S06-F10 percentile-rank redo with full downstream consumer audit

**Created:** 2026-04-28 (post-Q72 partial revert)
**Status:** OPEN

**Original finding:** S06-F10 — `regional_macro_service` percentile-rank on non-stationary level series saturated all funds at 100% percentile (CPIAUCSL ~300, PAYEMS in millions).

**Original fix (Q50-Q53 recovery, PR #356):** set `units="pc1"` on FRED fetch configs for non-stationary series. Stored YoY-percent values made percentile rank stationary.

**Codex catch (2026-04-28):** Q50-Q53 didn't audit downstream consumers. CPIAUCSL + PAYEMS are read by `regime_service.build_regime_inputs()` (recomputes YoY from levels) and `risk_calc._fetch_monthly_cpi_changes()` (MoM from levels). Double-transform corrupted regime + risk computations.

**Q72 partial revert:** CPIAUCSL + PAYEMS reverted to `units="lin"`. S06-F10 percentile-rank saturation regression accepted temporarily for these two series.

**TODO redo approach:**

1. Audit ALL downstream consumers of `macro_data` for the affected series:
   - INDPRO, PAYEMS, CPIAUCSL, PCEPILFE
   - CLVMNACSCAB1GQEA19, CP0000EZ19M086NEST
   - JPNRGDPEXP, JPNCPIALLMINMEI, CHNCPIALLMINMEI
   - BRACPIALLMINMEI, INDCPIALLMINMEI
2. For each consumer, decide:
   - Stop double-transform (read pc1 directly) — preferred
   - Or: read from lin-stored series elsewhere
3. Implement in-function YoY transform inside `regional_macro_service.score_global_indicators` / `score_region` for the percentile-rank purpose, so we don't need to mutate ingestion units
4. Revert remaining `units="pc1"` settings if downstream consumers prefer level data
5. New tests for each consumer ensuring no regression

**Effort estimate:** 1-2 sprints (multi-file consumer audit + careful redo).
