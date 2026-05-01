/**
 * Wealth-side re-export shim — Risk Methodology v3 institutional labels.
 *
 * The canonical implementation lives in
 * ``packages/ii-terminal-core/src/lib/i18n/quant-labels.ts``. This module
 * exists only so existing wealth call sites can keep importing from
 * ``$wealth/i18n/quant-labels`` without taking a hard dependency on the
 * terminal-core path. New code MAY import either path; both resolve to
 * the same module instance.
 *
 * Drift between this re-export, terminal-core, and the backend
 * dictionary in ``backend/app/domains/wealth/schemas/sanitized.py`` is
 * enforced by ``backend/tests/wealth/test_sanitization_parity.py``.
 *
 * PR-UX-5 — sanitization parity (canonize quant-labels + CI gate).
 */

export * from "@investintell/ii-terminal-core/i18n/quant-labels";
