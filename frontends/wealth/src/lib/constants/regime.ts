/** Regime display labels and colors — shared across dashboard and components. */

export const regimeLabels: Record<string, string> = {
	RISK_ON: "Risk On",
	RISK_OFF: "Risk Off",
	INFLATION: "Inflation",
	CRISIS: "Crisis",
};

export const regimeColors: Record<string, string> = {
	RISK_ON: "var(--ii-success)",
	RISK_OFF: "var(--ii-warning)",
	INFLATION: "var(--ii-brand-highlight)",
	CRISIS: "var(--ii-danger)",
};
