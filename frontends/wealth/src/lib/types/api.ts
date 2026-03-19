/** Wealth vertical API response types. */

// ── Regime ─────────────────────────────────────────────────

export interface RegimeData {
	regime: string;
	confidence: number | null;
	timestamp: string | null;
}

// ── Content ────────────────────────────────────────────────

export interface ContentSummary {
	id: string;
	content_type: string;
	status: string;
	created_at: string;
	title: string | null;
	created_by: string | null;
	error_message: string | null;
}

// ── Macro ──────────────────────────────────────────────────

export interface MacroScores {
	regions: { region: string; score: number; trend: string }[];
	global_indicators: Record<string, number>;
}

export interface RegimeHierarchy {
	global_regime: string;
	regions: { region: string; regime: string }[];
}

export interface MacroReview {
	id: string;
	status: string;
	created_at: string;
	summary: string | null;
}

// ── Instruments ────────────────────────────────────────────

export interface Instrument {
	id: string;
	ticker: string;
	name: string;
	asset_class: string;
	currency: string;
	last_price: number | null;
	exchange: string | null;
}

// ── DD Reports ─────────────────────────────────────────────

export interface DDReportSummary {
	report_id: string;
	status: string;
	version: number;
	confidence_score: number | null;
	decision_anchor: string | null;
	created_at: string;
	created_by: string | null;
	approved_by: string | null;
	approved_at: string | null;
	rejection_reason: string | null;
}

export interface DDReportChapter {
	id: string;
	chapter_tag: string;
	chapter_order: number;
	content_md: string | null;
	evidence_refs: Record<string, unknown> | null;
	quant_data: Record<string, unknown> | null;
	critic_iterations: number;
	critic_status: string;
	generated_at: string | null;
}

// ── Fund ───────────────────────────────────────────────────

export interface FundDetail {
	id: string;
	name: string;
	ticker: string | null;
	block: string | null;
	geography: string | null;
	asset_class: string | null;
	manager_score: number | null;
	isin: string | null;
	cnpj: string | null;
	inception_date: string | null;
}
