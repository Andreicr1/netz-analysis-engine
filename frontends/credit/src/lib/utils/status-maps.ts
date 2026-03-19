import type { StatusConfig } from "@netz/ui";

export const creditStatusMap: Record<string, StatusConfig> = {
	screening: { label: "Screening", severity: "neutral", color: "var(--netz-text-secondary)" },
	intake: { label: "Intake", severity: "neutral", color: "var(--netz-text-secondary)" },
	qualified: { label: "Qualified", severity: "info", color: "var(--netz-info)" },
	ic_review: { label: "IC Review", severity: "warning", color: "var(--netz-warning)" },
	conditional: { label: "Conditional", severity: "warning", color: "var(--netz-warning)" },
	approved: { label: "Approved", severity: "success", color: "var(--netz-success)" },
	converted_to_asset: { label: "Converted", severity: "success", color: "var(--netz-success)" },
	closed: { label: "Closed", severity: "neutral", color: "var(--netz-text-secondary)" },
	declined: { label: "Declined", severity: "danger", color: "var(--netz-danger)" },
	pending: { label: "Pending", severity: "warning", color: "var(--netz-warning)" },
	in_progress: { label: "In Progress", severity: "info", color: "var(--netz-info)" },
	rejected: { label: "Rejected", severity: "danger", color: "var(--netz-danger)" },
	revision_requested: {
		label: "Revision Requested",
		severity: "warning",
		color: "var(--netz-warning)",
	},
	low: { label: "Low", severity: "success", color: "var(--netz-success)" },
	medium: { label: "Medium", severity: "warning", color: "var(--netz-warning)" },
	high: { label: "High", severity: "danger", color: "var(--netz-danger)" },
	critical: { label: "Critical", severity: "danger", color: "var(--netz-danger)" },
};

export function resolveCreditStatus(token: string): StatusConfig | undefined {
	return creditStatusMap[token.trim().toLowerCase()];
}
