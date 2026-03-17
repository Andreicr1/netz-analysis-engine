/** Credit vertical API response types. */

// ── Dashboard ──────────────────────────────────────────────

export interface PortfolioSummary {
	total_aum: string | null;
	aum_trend: string | null;
	active_count: number;
	overdue_count: number;
}

export interface PipelineSummary {
	pending_ic: number;
	pending_ic_trend: string | null;
	docs_pending: number;
	ai_ready: number;
	converted_qtd: number;
}

export interface PipelineAnalytics {
	stages: Array<{ stage: string; count: number }>;
	conversion_rate: number | null;
}

export interface MacroSnapshot {
	treasury10y: string | null;
	baaSpread: string | null;
	yieldCurve: string | null;
	cpiYoy: string | null;
}

export interface TaskItem {
	id: string;
	title: string;
	type: string;
	priority: string;
	due_date: string | null;
}

// ── Fund / Deal ────────────────────────────────────────────

export interface DealDetail {
	name: string;
	stage: string;
	strategy_type: string | null;
	borrower_name: string | null;
	amount: string | null;
	created_at: string | null;
}

export interface StageTimelineEntry {
	stage: string;
	entered_at: string;
	completed_at: string | null;
}

// ── Portfolio ──────────────────────────────────────────────

export interface PaginatedResponse<T> {
	items: T[];
	total: number;
}

export interface PortfolioAsset {
	name: string;
	asset_type: string;
	strategy: string;
	status: string;
}

export interface PortfolioObligation {
	type: string;
	due_date: string;
	status: string;
	asset_name: string;
}

export interface PortfolioAlert {
	severity: string;
	message: string;
	asset_name: string;
	created_at: string;
}

export interface PortfolioAction {
	title: string;
	status: string;
	due_date: string | null;
	evidence_notes: string | null;
}

// ── Documents ──────────────────────────────────────────────

export interface DocumentItem {
	title: string;
	root_folder: string;
	domain: string;
	status: string;
	created_at: string;
}

// ── Reviews ────────────────────────────────────────────────

export interface ReviewItem {
	document_title: string;
	document_type: string;
	status: string;
	priority: string;
	created_at: string;
}

export interface ReviewSummary {
	pending: number;
	under_review: number;
	approved: number;
	rejected: number;
}

export interface ReviewDetail {
	document_title: string | null;
	status: string;
	assignments: ReviewAssignment[];
}

export interface ReviewAssignment {
	reviewer_name: string;
	decision: string;
}

export interface ReviewChecklist {
	items: ChecklistItem[];
}

export interface ChecklistItem {
	checked: boolean;
	description: string;
}

// ── Reporting ──────────────────────────────────────────────

export interface NavSnapshot {
	reference_date: string;
	status: string;
	total_nav: string;
	created_at: string;
}

export interface ReportPack {
	period: string;
	status: string;
	created_at: string;
}

// ── IC Memo ────────────────────────────────────────────────

export interface ICMemo {
	status: string;
	chapters: ICMemoChapter[];
}

export interface ICMemoChapter {
	chapter_number: number;
	title: string;
	content: string;
	status: string;
}

export interface VotingStatus {
	status: string;
	votes_cast: number;
	quorum: number;
}

// ── Copilot ────────────────────────────────────────────────

export interface Citation {
	url: string | null;
	document_title: string | null;
	source: string | null;
	page_number: number | null;
}
