import type { StatusConfig } from "../components/analytical/StatusBadge.svelte";

// -- Tenant status -----------------------------------------------------------
const tenantStatusMap: Record<string, StatusConfig> = {
	active: { label: "Active", severity: "success", color: "var(--ii-success)" },
	suspended: { label: "Suspended", severity: "warning", color: "var(--ii-warning)" },
	archived: { label: "Archived", severity: "neutral", color: "var(--ii-text-secondary)" },
};

// -- Service / worker health -------------------------------------------------
const serviceHealthMap: Record<string, StatusConfig> = {
	ok: { label: "OK", severity: "success", color: "var(--ii-success)" },
	healthy: { label: "Healthy", severity: "success", color: "var(--ii-success)" },
	degraded: { label: "Degraded", severity: "warning", color: "var(--ii-warning)" },
	warn: { label: "Warning", severity: "warning", color: "var(--ii-warning)" },
	error: { label: "Error", severity: "danger", color: "var(--ii-danger)" },
	failed: { label: "Failed", severity: "danger", color: "var(--ii-danger)" },
	critical: { label: "Critical", severity: "danger", color: "var(--ii-danger)" },
	running: { label: "Running", severity: "info", color: "var(--ii-info)" },
	checking: { label: "Checking", severity: "info", color: "var(--ii-info)" },
};

// -- Config vertical ---------------------------------------------------------
const configVerticalMap: Record<string, StatusConfig> = {
	private_credit: { label: "Private Credit", severity: "info", color: "var(--ii-info)" },
	liquid_funds: { label: "Liquid Funds", severity: "info", color: "var(--ii-info)" },
};

// -- Pipeline stage ----------------------------------------------------------
const pipelineStageMap: Record<string, StatusConfig> = {
	processing: { label: "Processing", severity: "info", color: "var(--ii-info)" },
	complete: { label: "Complete", severity: "success", color: "var(--ii-success)" },
	failed: { label: "Failed", severity: "danger", color: "var(--ii-danger)" },
};

// -- Merged lookup table -----------------------------------------------------
const adminStatusMap: Record<string, StatusConfig> = {
	...tenantStatusMap,
	...serviceHealthMap,
	...configVerticalMap,
	...pipelineStageMap,
};

export function resolveAdminStatus(token: string): StatusConfig | undefined {
	return adminStatusMap[token.trim().toLowerCase()];
}
