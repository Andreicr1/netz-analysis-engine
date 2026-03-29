import type { StatusConfig } from "@investintell/ui";

export const wealthStatusMap: Record<string, StatusConfig> = {
	risk_on: { label: "Risk On", severity: "success", color: "var(--ii-success)" },
	risk_off: { label: "Risk Off", severity: "warning", color: "var(--ii-warning)" },
	inflation: { label: "Inflation", severity: "warning", color: "var(--ii-warning)" },
	crisis: { label: "Crisis", severity: "danger", color: "var(--ii-danger)" },
	pass: { label: "Pass", severity: "success", color: "var(--ii-success)" },
	watchlist: { label: "Watchlist", severity: "warning", color: "var(--ii-warning)" },
	fail: { label: "Fail", severity: "danger", color: "var(--ii-danger)" },
	pending_approval: { label: "Awaiting IC Approval", severity: "warning", color: "var(--ii-warning)" },
	pending_review: { label: "Pending Review", severity: "info", color: "var(--ii-info)" },
	pending: { label: "Pending", severity: "warning", color: "var(--ii-warning)" },
	approved: { label: "Approved", severity: "success", color: "var(--ii-success)" },
	published: { label: "Published", severity: "success", color: "var(--ii-success)" },
	rejected: { label: "Rejected", severity: "danger", color: "var(--ii-danger)" },
	draft: { label: "Draft", severity: "neutral", color: "var(--ii-text-muted)" },
	review: { label: "In Review", severity: "info", color: "var(--ii-info)" },
	generating: { label: "Generating", severity: "info", color: "var(--ii-info)" },
	completed: { label: "Completed", severity: "success", color: "var(--ii-success)" },
	// Rebalancing workflow tokens
	proposed: { label: "Proposed", severity: "info", color: "var(--ii-info)" },
	executing: { label: "Executing", severity: "info", color: "var(--ii-info)" },
	executed: { label: "Executed", severity: "success", color: "var(--ii-success)" },
	partial: { label: "Partial", severity: "warning", color: "var(--ii-warning)" },
	failed: { label: "Failed", severity: "danger", color: "var(--ii-danger)" },
	warning: { label: "Warning", severity: "warning", color: "var(--ii-warning)" },
	breach: { label: "Breach", severity: "danger", color: "var(--ii-danger)" },
	// Drift severity tokens
	low: { label: "Low", severity: "success", color: "var(--ii-success)" },
	medium: { label: "Medium", severity: "warning", color: "var(--ii-warning)" },
	high: { label: "High", severity: "danger", color: "var(--ii-danger)" },
	critical: { label: "Critical", severity: "danger", color: "var(--ii-danger)" },
};

export function resolveWealthStatus(token: string): StatusConfig | undefined {
	return wealthStatusMap[token.trim().toLowerCase()];
}
