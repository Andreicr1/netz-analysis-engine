/**
 * PR-A26.3 — Allocation page types.
 *
 * Maps 1:1 to backend Pydantic schemas in
 * ``backend/app/domains/wealth/schemas/model_portfolio.py``
 * (StrategicAllocationResponse / ApprovalHistoryResponse and friends).
 *
 * Hand-maintained until ``make types`` (openapi-typescript) is wired
 * into the frontend build — matches the pattern of model-portfolio.ts.
 */

export interface StrategicAllocationBlock {
	block_id: string;
	block_name: string;
	target_weight: number | null;
	drift_min: number | null;
	drift_max: number | null;
	override_min: number | null;
	override_max: number | null;
	excluded_from_portfolio: boolean;
	approved_from_run_id: string | null;
	approved_at: string | null;
	approved_by: string | null;
}

export interface StrategicAllocationResponse {
	organization_id: string;
	profile: string;
	cvar_limit: number;
	has_active_approval: boolean;
	last_approved_at: string | null;
	last_approved_by: string | null;
	blocks: StrategicAllocationBlock[];
}

export interface ApprovalHistoryEntry {
	approval_id: string;
	run_id: string;
	approved_by: string;
	approved_at: string;
	superseded_at: string | null;
	cvar_at_approval: number | null;
	expected_return_at_approval: number | null;
	cvar_feasible_at_approval: boolean;
	operator_message: string | null;
	is_active: boolean;
}

export interface ApprovalHistoryResponse {
	organization_id: string;
	profile: string;
	total: number;
	entries: ApprovalHistoryEntry[];
}

export interface ProposedBand {
	block_id: string;
	target_weight: number;
	drift_min: number;
	drift_max: number;
	rationale: string | null;
}

export interface ProposalMetrics {
	expected_return: number | null;
	expected_cvar: number | null;
	expected_sharpe: number | null;
	target_cvar: number | null;
	cvar_feasible: boolean;
}

export interface LatestProposalResponse {
	run_id: string;
	requested_at: string;
	winner_signal: string;
	proposed_bands: ProposedBand[];
	proposal_metrics: ProposalMetrics;
}

export interface JobCreatedResponse {
	job_id: string;
	sse_url: string;
	run_id: string;
}

export interface ApproveProposalRequest {
	confirm_cvar_infeasible?: boolean;
	operator_message?: string | null;
}

export interface SetOverrideRequest {
	block_id: string;
	override_min: number | null;
	override_max: number | null;
	rationale: string | null;
}

export type AllocationProfile = "conservative" | "moderate" | "growth";

export const ALLOCATION_PROFILES: readonly AllocationProfile[] = [
	"conservative",
	"moderate",
	"growth",
] as const;

export const PROFILE_LABELS: Record<AllocationProfile, string> = {
	conservative: "Conservative",
	moderate: "Moderate",
	growth: "Growth",
};

/** Block family grouping — drives donut/chart color buckets. */
export type BlockFamily = "equity" | "fixed_income" | "alternatives" | "cash";

export function blockFamily(block_id: string): BlockFamily {
	if (block_id === "cash") return "cash";
	if (block_id.startsWith("fi_")) return "fixed_income";
	if (block_id.startsWith("alt_")) return "alternatives";
	return "equity";
}
