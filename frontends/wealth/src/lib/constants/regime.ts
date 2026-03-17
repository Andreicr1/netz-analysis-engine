/** Regime display labels and colors — shared across dashboard and components. */

export const regimeLabels: Record<string, string> = {
	RISK_ON: "Risk On",
	RISK_OFF: "Risk Off",
	INFLATION: "Inflation",
	CRISIS: "Crisis",
};

export const regimeColors: Record<string, string> = {
	RISK_ON: "var(--netz-success)",
	RISK_OFF: "var(--netz-warning)",
	INFLATION: "var(--netz-brand-highlight)",
	CRISIS: "var(--netz-danger)",
};
