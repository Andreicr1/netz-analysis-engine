/** Regime display labels, colors, and CVaR multipliers — shared across dashboard and components. */

export const regimeLabels: Record<string, string> = {
	RISK_ON: "Expansion",
	RISK_OFF: "Defensive",
	INFLATION: "Inflation",
	CRISIS: "Stress",
};

export const regimeColors: Record<string, string> = {
	RISK_ON: "var(--ii-success)",
	RISK_OFF: "var(--ii-warning)",
	INFLATION: "var(--ii-brand-highlight)",
	CRISIS: "var(--ii-danger)",
};

export const REGIME_CVAR_MULTIPLIER: Record<string, number> = {
	RISK_ON: 1.00,
	RISK_OFF: 0.85,
	CRISIS: 0.70,
	INFLATION: 0.90,
};

export function regimeMultiplierLabel(regime: string): string {
	const m = REGIME_CVAR_MULTIPLIER[regime];
	if (!m || m === 1.0) return "";
	const pct = Math.round((1 - m) * 100);
	return `Risk budget tightened by ${pct}%`;
}
