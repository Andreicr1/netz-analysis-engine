import type { StatusConfig } from "../components/StatusBadge.svelte";

// ── Tenant status ─────────────────────────────────────────────────────────────
const tenantStatusMap: Record<string, StatusConfig> = {
	active: { label: "Active", severity: "success", color: "var(--netz-success)" },
	suspended: { label: "Suspended", severity: "warning", color: "var(--netz-warning)" },
	archived: { label: "Archived", severity: "neutral", color: "var(--netz-text-secondary)" },
};

// ── Service / worker health ───────────────────────────────────────────────────
const serviceHealthMap: Record<string, StatusConfig> = {
	ok: { label: "OK", severity: "success", color: "var(--netz-success)" },
	healthy: { label: "Healthy", severity: "success", color: "var(--netz-success)" },
	degraded: { label: "Degraded", severity: "warning", color: "var(--netz-warning)" },
	warn: { label: "Warning", severity: "warning", color: "var(--netz-warning)" },
	error: { label: "Error", severity: "danger", color: "var(--netz-danger)" },
	failed: { label: "Failed", severity: "danger", color: "var(--netz-danger)" },
	critical: { label: "Critical", severity: "danger", color: "var(--netz-danger)" },
	running: { label: "Running", severity: "info", color: "var(--netz-info)" },
	checking: { label: "Checking", severity: "info", color: "var(--netz-info)" },
};

// ── Config vertical ───────────────────────────────────────────────────────────
const configVerticalMap: Record<string, StatusConfig> = {
	private_credit: { label: "Private Credit", severity: "info", color: "var(--netz-info)" },
	liquid_funds: { label: "Liquid Funds", severity: "info", color: "var(--netz-info)" },
};

// ── Pipeline stage ────────────────────────────────────────────────────────────
const pipelineStageMap: Record<string, StatusConfig> = {
	processing: { label: "Processing", severity: "info", color: "var(--netz-info)" },
	complete: { label: "Complete", severity: "success", color: "var(--netz-success)" },
	failed: { label: "Failed", severity: "danger", color: "var(--netz-danger)" },
};

// ── Merged lookup table ───────────────────────────────────────────────────────
const adminStatusMap: Record<string, StatusConfig> = {
	...tenantStatusMap,
	...serviceHealthMap,
	...configVerticalMap,
	...pipelineStageMap,
};

export function resolveAdminStatus(token: string): StatusConfig | undefined {
	return adminStatusMap[token.trim().toLowerCase()];
}
