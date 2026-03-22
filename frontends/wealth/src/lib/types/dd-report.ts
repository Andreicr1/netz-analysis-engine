/** DD Report domain types — maps 1:1 to backend schemas. */

export type DDReportStatus =
	| "draft"
	| "generating"
	| "pending_approval"
	| "approved"
	| "rejected"
	| "failed";

export type DecisionAnchor = "APPROVE" | "CONDITIONAL" | "REJECT";

export interface DDChapter {
	id: string;
	chapter_tag: string;
	chapter_order: number;
	content_md: string | null;
	evidence_refs: Record<string, unknown> | null;
	quant_data: Record<string, unknown> | null;
	critic_iterations: number;
	critic_status: "pending" | "accepted" | "escalated";
	generated_at: string | null;
}

export interface DDReportSummary {
	id: string;
	instrument_id: string;
	report_type: "dd_report" | "bond_brief";
	version: number;
	status: DDReportStatus;
	confidence_score: number | null;
	decision_anchor: DecisionAnchor | null;
	is_current: boolean;
	created_at: string;
	created_by: string | null;
	approved_by: string | null;
	approved_at: string | null;
	rejection_reason: string | null;
}

export interface DDReportFull extends DDReportSummary {
	config_snapshot: Record<string, unknown> | null;
	schema_version: number;
	chapters: DDChapter[];
}

/** Chapter registry — mirrors backend CHAPTER_REGISTRY order */
export const CHAPTER_TITLES: Record<string, string> = {
	executive_summary: "Executive Summary",
	investment_strategy: "Investment Strategy & Process",
	manager_assessment: "Fund Manager Assessment",
	performance_analysis: "Performance Analysis",
	risk_framework: "Risk Management Framework",
	fee_analysis: "Fee Analysis",
	operational_dd: "Operational Due Diligence",
	recommendation: "Recommendation",
};

export function chapterTitle(tag: string): string {
	return CHAPTER_TITLES[tag] ?? tag.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function anchorLabel(anchor: DecisionAnchor | null): string {
	switch (anchor) {
		case "APPROVE": return "Approve";
		case "CONDITIONAL": return "Conditional";
		case "REJECT": return "Reject";
		default: return "—";
	}
}

export function confidenceColor(score: number | null): string {
	if (score === null) return "var(--netz-text-muted)";
	if (score >= 80) return "var(--netz-success)";
	if (score >= 60) return "var(--netz-info)";
	return "var(--netz-warning)";
}

export function anchorColor(anchor: DecisionAnchor | null): string {
	switch (anchor) {
		case "APPROVE": return "var(--netz-success)";
		case "CONDITIONAL": return "var(--netz-warning)";
		case "REJECT": return "var(--netz-danger)";
		default: return "var(--netz-text-muted)";
	}
}
