/** SEC Fund types — registered fund catalog, detail, holdings, style. */

// ── Registered Funds ────────────────────────────────────────────────────

export interface RegisteredFundSummary {
	cik: string;
	fund_name: string;
	fund_type: string;
	ticker: string | null;
	total_assets: number | null;
	last_nport_date: string | null;
	style_label: string | null;
	style_confidence: number | null;
}

export interface RegisteredFundListResponse {
	funds: RegisteredFundSummary[];
	total: number;
}

// ── Private Funds ───────────────────────────────────────────────────────

export interface PrivateFundSummary {
	fund_name: string;
	fund_type: string | null;
	gross_asset_value: number | null;
	investor_count: number | null;
	is_fund_of_funds: boolean | null;
}

export interface PrivateFundListResponse {
	funds: PrivateFundSummary[];
	total: number;
}

// ── Fund Detail ─────────────────────────────────────────────────────────

export interface FundFirmInfo {
	crd_number: string;
	firm_name: string;
	aum_total: number | null;
	compliance_disclosures: number | null;
	state: string | null;
	website: string | null;
}

export interface FundTeamMember {
	person_name: string;
	title: string | null;
	role: string | null;
	years_experience: number | null;
	certifications: string[];
}

export interface FundStyleInfo {
	style_label: string;
	growth_tilt: number;
	sector_weights: Record<string, number>;
	equity_pct: number | null;
	fixed_income_pct: number | null;
	cash_pct: number | null;
	confidence: number;
	report_date: string;
}

export interface FundDataAvailability {
	fund_universe: string;
	has_holdings: boolean;
	has_nav_history: boolean;
	has_style_analysis: boolean;
	has_portfolio_manager: boolean;
	has_peer_analysis: boolean;
	disclosure_note: string | null;
}

export interface FundDetailResponse {
	cik: string;
	fund_name: string;
	fund_type: string;
	ticker: string | null;
	isin: string | null;
	total_assets: number | null;
	total_shareholder_accounts: number | null;
	inception_date: string | null;
	currency: string;
	domicile: string;
	last_nport_date: string | null;
	firm: FundFirmInfo | null;
	team: FundTeamMember[];
	latest_style: FundStyleInfo | null;
	data_availability: FundDataAvailability;
}

// ── Holdings (N-PORT) ───────────────────────────────────────────────────

export interface NportHoldingItem {
	cusip: string | null;
	isin: string | null;
	issuer_name: string | null;
	asset_class: string | null;
	sector: string | null;
	market_value: number | null;
	pct_of_nav: number | null;
	quantity: number | null;
	currency: string | null;
	fair_value_level: string | null;
}

export interface NportHoldingsPage {
	holdings: NportHoldingItem[];
	available_quarters: string[];
	total_count: number;
	total_value: number | null;
}

// ── Style History ───────────────────────────────────────────────────────

export interface StyleSnapshotItem {
	report_date: string;
	style_label: string;
	growth_tilt: number;
	sector_weights: Record<string, number>;
	equity_pct: number | null;
	fixed_income_pct: number | null;
	cash_pct: number | null;
	confidence: number;
}

export interface StyleHistoryResponse {
	snapshots: StyleSnapshotItem[];
	drift_detected: boolean;
	quarters_analyzed: number;
}

// ── Defaults ────────────────────────────────────────────────────────────

export const EMPTY_REGISTERED_FUNDS: RegisteredFundListResponse = { funds: [], total: 0 };
export const EMPTY_PRIVATE_FUNDS: PrivateFundListResponse = { funds: [], total: 0 };
export const EMPTY_HOLDINGS: NportHoldingsPage = {
	holdings: [],
	available_quarters: [],
	total_count: 0,
	total_value: null,
};
export const EMPTY_STYLE_HISTORY: StyleHistoryResponse = {
	snapshots: [],
	drift_detected: false,
	quarters_analyzed: 0,
};
