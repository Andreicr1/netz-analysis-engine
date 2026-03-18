import type { StatusConfig } from "@netz/ui";

export const wealthStatusMap: Record<string, StatusConfig> = {
	risk_on: { label: "Risk On", severity: "success", color: "var(--netz-success)" },
	risk_off: { label: "Risk Off", severity: "warning", color: "var(--netz-warning)" },
	inflation: { label: "Inflation", severity: "warning", color: "var(--netz-warning)" },
	crisis: { label: "Crisis", severity: "danger", color: "var(--netz-danger)" },
	pass: { label: "Pass", severity: "success", color: "var(--netz-success)" },
	watchlist: { label: "Watchlist", severity: "warning", color: "var(--netz-warning)" },
	fail: { label: "Fail", severity: "danger", color: "var(--netz-danger)" },
	approved: { label: "Approved", severity: "success", color: "var(--netz-success)" },
	published: { label: "Published", severity: "success", color: "var(--netz-success)" },
	warning: { label: "Warning", severity: "warning", color: "var(--netz-warning)" },
	breach: { label: "Breach", severity: "danger", color: "var(--netz-danger)" },
};

export function resolveWealthStatus(token: string): StatusConfig | undefined {
	return wealthStatusMap[token.trim().toLowerCase()];
}
