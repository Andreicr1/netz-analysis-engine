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

export type DealType = "DIRECT_LOAN" | "FUND_INVESTMENT" | "EQUITY_STAKE" | "SPV_NOTE";

export type DealStage =
	| "INTAKE" | "QUALIFIED" | "IC_REVIEW" | "CONDITIONAL"
	| "APPROVED" | "CONVERTED_TO_ASSET" | "REJECTED" | "CLOSED";

export type RejectionCode =
	| "OUT_OF_MANDATE" | "TICKET_TOO_SMALL" | "JURISDICTION_EXCLUDED"
	| "INSUFFICIENT_RETURN" | "WEAK_CREDIT_PROFILE" | "NO_COLLATERAL";

export interface DealDetail {
	id: string;
	fund_id: string;
	name: string;
	deal_type: DealType;
	stage: DealStage;
	strategy_type: string | null;
	borrower_name: string | null;
	sponsor_name: string | null;
	description: string | null;
	amount: string | null;
	rejection_code: RejectionCode | null;
	rejection_notes: string | null;
	asset_id: string | null;
	created_at: string | null;
	updated_at: string | null;
}

export interface StageTimeline {
	dealId: string;
	currentStage: DealStage;
	nodes: StageTimelineNode[];
	allowedTransitions: DealStage[];
	timeline: StageTimelineEvent[];
}

export interface StageTimelineNode {
	stage: string;
	state: "Positive" | "Critical" | "Neutral" | "Negative";
	reachedAt: string | null;
	rationale: string | null;
}

export interface StageTimelineEvent {
	fromStage: string;
	toStage: string;
	changedAt: string | null;
	rationale: string | null;
}

export interface StageTimelineEntry {
	stage: string;
	entered_at: string;
	completed_at: string | null;
}

// ── IC Memo Detail ────────────────────────────────────────

export interface ICMemoDetail {
	id: string;
	deal_id: string;
	executive_summary: string;
	risks: string | null;
	mitigants: string | null;
	recommendation: string | null;
	conditions: ICCondition[];
	version: number;
	condition_history: Record<string, unknown>[];
	created_at: string;
	updated_at: string;
}

export interface ICCondition {
	id: string;
	title: string;
	status: "open" | "resolved" | "waived";
	resolved_at?: string;
	resolved_by?: string;
	notes?: string;
	evidence_docs?: string[];
}

export interface VotingStatusDetail {
	memoId: string;
	version: number;
	recommendation: string | null;
	esignatureStatus: string | null;
	votingState: string;
	quorum: {
		totalMembers: number;
		majorityRequired: number;
		votesCast: number;
		approvals: number;
		rejections: number;
		pending: number;
		quorumReached: boolean;
	};
	members: Array<{
		email: string;
		vote: string | null;
		signedAt: string | null;
		signerStatus: string | null;
	}>;
	conditions: {
		total: number;
		open: number;
		resolved: number;
		allResolved: boolean;
		items: ICCondition[];
	};
	conditionHistory: Record<string, unknown>[];
}

// ── Portfolio ──────────────────────────────────────────────

export interface PaginatedResponse<T> {
	items: T[];
	total: number;
}

export type AssetType = "DIRECT_LOAN" | "FUND_INVESTMENT" | "EQUITY_STAKE" | "SPV_NOTE";
export type Strategy = "CORE_DIRECT_LENDING" | "OPPORTUNISTIC" | "DISTRESSED" | "VENTURE_DEBT" | "FUND_OF_FUNDS";
export type ObligationType = "NAV_REPORT" | "COVENANT_TEST" | "FINANCIAL_STATEMENT" | "AUDIT_REPORT" | "COMPLIANCE_CERT";
export type ObligationStatus = "OPEN" | "FULFILLED" | "OVERDUE" | "WAIVED";
export type ActionStatus = "OPEN" | "IN_PROGRESS" | "CLOSED";

export interface PortfolioAsset {
	id: string;
	fund_id: string;
	name: string;
	asset_type: AssetType;
	strategy: Strategy;
	status: string;
	created_at: string;
	updated_at: string;
}

export interface PortfolioObligation {
	id: string;
	asset_id: string;
	obligation_type: ObligationType;
	type: string;
	due_date: string;
	status: ObligationStatus;
	asset_name: string;
	created_at: string;
	updated_at: string;
}

export interface PortfolioAlert {
	severity: string;
	message: string;
	asset_name: string;
	created_at: string;
}

export interface PortfolioAction {
	id: string;
	asset_id: string;
	title: string;
	status: ActionStatus;
	due_date: string | null;
	evidence_notes: string | null;
	created_at: string;
	updated_at: string;
}

// ── Documents ──────────────────────────────────────────────

export interface DocumentItem {
	id: string;
	title: string;
	root_folder: string;
	domain: string;
	status: string;
	created_at: string;
	classification_layer: number | null;
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
	id: string;
	period: string;
	period_start: string;
	period_end: string;
	status: "DRAFT" | "GENERATED" | "PUBLISHED";
	created_at: string;
	published_at: string | null;
}

// ── IC Memo ────────────────────────────────────────────────

/** Mirrors components["schemas"]["CommitteeVoteOut"] from api.d.ts */
export interface CommitteeVoteOut {
	email: string;
	vote: string;
	signed_at?: string | null;
	signer_status?: string | null;
	actor_capacity?: string | null;
	rationale?: string | null;
}

export interface ICMemo {
	status: string;
	chapters: ICMemoChapter[];
	committee_votes?: CommitteeVoteOut[] | null;
	esignature_status?: string | null;
}

export interface ICMemoChapter {
	chapter_number: number;
	title: string;
	content: string;
	status: string;
	model_version?: string | null;
	generated_at?: string | null;
}

// ── Evidence Pack ───────────────────────────────────────────

export interface EvidenceCitation {
	blob_name: string;
	doc_type: string;
	page_start: number | null;
	page_end: number | null;
	chunk_id: string;
	score: number | null;
}

export interface EvidencePack {
	dealId: string;
	evidencePackId: string;
	versionTag: string | null;
	tokenCount: number | null;
	generatedAt: string | null;
	modelVersion: string | null;
	evidenceJson: {
		citations?: EvidenceCitation[];
		[key: string]: unknown;
	};
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
