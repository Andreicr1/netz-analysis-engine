/**
 * TAA (Tactical Asset Allocation) frontend types.
 * Mirrors backend schemas from `allocation.py` Sprint 3.
 */

export interface EffectiveBand {
	min: number;
	max: number;
	center: number | null;
}

export interface RegimeBands {
	profile: string;
	as_of_date: string;
	raw_regime: string;
	stress_score: number | null;
	smoothed_centers: Record<string, number>;
	effective_bands: Record<string, EffectiveBand>;
	transition_velocity: Record<string, number> | null;
	ips_clamps_applied: string[];
	taa_enabled: boolean;
}

export interface TaaHistoryRow {
	as_of_date: string;
	raw_regime: string;
	stress_score: number | null;
	smoothed_centers: Record<string, number>;
	effective_bands: Record<string, Record<string, number>>;
	transition_velocity: Record<string, number> | null;
	created_at: string;
}

export interface TaaHistory {
	profile: string;
	rows: TaaHistoryRow[];
	total: number;
}

export interface EffectiveAllocationWithRegime {
	profile: string;
	block_id: string;
	strategic_weight: number | null;
	tactical_overweight: number | null;
	effective_weight: number | null;
	min_weight: number | null;
	max_weight: number | null;
	regime_min: number | null;
	regime_max: number | null;
	regime_center: number | null;
}

/**
 * OD-22 translated regime labels for institutional display.
 * Backend emits RISK_ON/RISK_OFF/CRISIS/INFLATION.
 * Frontend shows Expansion/Defensive/Stress/Inflation.
 */
export const TAA_REGIME_LABELS: Record<string, string> = {
	RISK_ON: "Expansion",
	RISK_OFF: "Defensive",
	CRISIS: "Stress",
	INFLATION: "Inflation",
};

export function taaRegimeLabel(raw: string): string {
	return TAA_REGIME_LABELS[raw] ?? raw;
}

/**
 * Regime posture description — one-liner institutional summary.
 * Shown below the regime badge in the CalibrationPanel.
 */
export const TAA_REGIME_POSTURE: Record<string, string> = {
	RISK_ON: "Growth-oriented allocation bands active",
	RISK_OFF: "Defensive posture — reduced equity exposure",
	CRISIS: "Stress posture — maximum capital preservation",
	INFLATION: "Inflation hedge tilt — real assets favored",
};

export function taaRegimePosture(raw: string): string {
	return TAA_REGIME_POSTURE[raw] ?? "Allocation bands adjusted to current conditions";
}

/**
 * Regime color tokens — CSS variable references for institutional palette.
 */
export const TAA_REGIME_COLORS: Record<string, string> = {
	RISK_ON: "var(--ii-success)",
	RISK_OFF: "var(--ii-warning)",
	CRISIS: "var(--ii-danger)",
	INFLATION: "var(--ii-brand-highlight)",
};

export function taaRegimeColor(raw: string): string {
	return TAA_REGIME_COLORS[raw] ?? "var(--ii-text-muted)";
}
