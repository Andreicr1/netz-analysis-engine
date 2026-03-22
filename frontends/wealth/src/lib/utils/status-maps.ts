import type { StatusConfig } from "@netz/ui";

export const wealthStatusMap: Record<string, StatusConfig> = {
	risk_on: { label: "Risk On", severity: "success", color: "var(--netz-success)" },
	risk_off: { label: "Risk Off", severity: "warning", color: "var(--netz-warning)" },
	inflation: { label: "Inflation", severity: "warning", color: "var(--netz-warning)" },
	crisis: { label: "Crisis", severity: "danger", color: "var(--netz-danger)" },
	pass: { label: "Pass", severity: "success", color: "var(--netz-success)" },
	watchlist: { label: "Watchlist", severity: "warning", color: "var(--netz-warning)" },
	fail: { label: "Fail", severity: "danger", color: "var(--netz-danger)" },
	pending_approval: { label: "Awaiting IC Approval", severity: "warning", color: "var(--netz-warning)" },
	pending_review: { label: "Pending Review", severity: "info", color: "var(--netz-info)" },
	pending: { label: "Pending", severity: "warning", color: "var(--netz-warning)" },
	approved: { label: "Approved", severity: "success", color: "var(--netz-success)" },
	published: { label: "Published", severity: "success", color: "var(--netz-success)" },
	rejected: { label: "Rejected", severity: "danger", color: "var(--netz-danger)" },
	draft: { label: "Draft", severity: "neutral", color: "var(--netz-text-muted)" },
	review: { label: "In Review", severity: "info", color: "var(--netz-info)" },
	generating: { label: "Generating", severity: "info", color: "var(--netz-info)" },
	completed: { label: "Completed", severity: "success", color: "var(--netz-success)" },
	// Rebalancing workflow tokens
	proposed: { label: "Proposed", severity: "info", color: "var(--netz-info)" },
	executing: { label: "Executing", severity: "info", color: "var(--netz-info)" },
	executed: { label: "Executed", severity: "success", color: "var(--netz-success)" },
	partial: { label: "Partial", severity: "warning", color: "var(--netz-warning)" },
	failed: { label: "Failed", severity: "danger", color: "var(--netz-danger)" },
	warning: { label: "Warning", severity: "warning", color: "var(--netz-warning)" },
	breach: { label: "Breach", severity: "danger", color: "var(--netz-danger)" },
	// Drift severity tokens
	low: { label: "Low", severity: "success", color: "var(--netz-success)" },
	medium: { label: "Medium", severity: "warning", color: "var(--netz-warning)" },
	high: { label: "High", severity: "danger", color: "var(--netz-danger)" },
	critical: { label: "Critical", severity: "danger", color: "var(--netz-danger)" },
};

export function resolveWealthStatus(token: string): StatusConfig | undefined {
	return wealthStatusMap[token.trim().toLowerCase()];
}
