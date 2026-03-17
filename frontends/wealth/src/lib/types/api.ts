/** Wealth vertical API response types. */

// ── Regime ─────────────────────────────────────────────────

export interface RegimeData {
	regime: string;
	confidence: number | null;
	timestamp: string | null;
}
