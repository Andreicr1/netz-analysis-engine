/** Manager Screener domain types — SEC EDGAR integration. */

export interface ManagerRow {
	crd_number: string;
	firm_name: string;
	aum_total: number | null;
	registration_status: string | null;
	state: string | null;
	country: string | null;
	compliance_disclosures: number | null;
	top_sectors: Record<string, number>;
	hhi: number | null;
	position_count: number | null;
	drift_churn: number | null;
	has_institutional_holders: boolean;
	universe_status: string | null;
}

export interface ScreenerPage {
	managers: ManagerRow[];
	total_count: number;
	page: number;
	page_size: number;
	has_next: boolean;
}

export interface ManagerProfile {
	crd_number: string;
	cik: string | null;
	firm_name: string;
	sec_number: string | null;
	registration_status: string | null;
	aum_total: number | null;
	aum_discretionary: number | null;
	aum_non_discretionary: number | null;
	total_accounts: number | null;
	fee_types: Record<string, boolean> | null;
	client_types: Record<string, boolean> | null;
	state: string | null;
	country: string | null;
	website: string | null;
	compliance_disclosures: number | null;
	last_adv_filed_at: string | null;
	funds: { fund_name: string; gross_asset_value: number | null; fund_type: string | null }[];
	team: { person_name: string; title: string | null; role: string | null }[];
}

export interface HoldingsData {
	sector_allocation: Record<string, number>;
	top_holdings: {
		cusip: string;
		issuer_name: string;
		sector: string | null;
		market_value: number | null;
		weight: number | null;
	}[];
	hhi: number | null;
}

export interface InstitutionalData {
	coverage_type: string;
	holders: {
		filer_name: string;
		filer_type: string | null;
		filer_cik: string;
		market_value: number | null;
	}[];
}

export interface UniverseStatus {
	instrument_id: string | null;
	approval_status: string | null;
	asset_class: string | null;
	geography: string | null;
	currency: string | null;
	block_id: string | null;
	added_at: string | null;
}

export interface CompareResult {
	managers: ManagerProfile[];
	sector_allocations: Record<string, Record<string, number>>;
	jaccard_overlap: number;
}

export type DetailTab = "profile" | "holdings" | "institutional" | "universe" | "registered" | "drift" | "nport" | "docs" | "brochure";

// ── Registered Funds tab ──
export interface ManagerRegisteredFundItem {
	cik: string;
	fund_name: string;
	fund_type: string;
	ticker: string | null;
	isin: string | null;
	total_assets: number | null;
	inception_date: string | null;
	last_nport_date: string | null;
	aum_below_threshold: boolean;
	already_in_universe: boolean;
	universe_instrument_id: string | null;
}

export interface ManagerRegisteredFundsResponse {
	crd_number: string;
	firm_name: string;
	funds: ManagerRegisteredFundItem[];
	total_funds: number;
}

// ── Drift tab ──
export interface DriftQuarter {
	quarter: string;
	turnover: number;
	new_positions: number;
	exited_positions: number;
	increased: number;
	decreased: number;
	unchanged: number;
	total_changes: number;
}

export interface ManagerDriftData {
	quarters: DriftQuarter[];
	style_drift_detected: boolean;
}

// ── N-PORT tab ──
export interface NportHoldingItem {
	cusip: string | null;
	isin: string | null;
	issuer_name: string;
	asset_class: string | null;
	sector: string | null;
	market_value: number | null;
	quantity: number | null;
	currency: string | null;
	pct_of_nav: number | null;
	report_date: string;
}

export interface NportHoldingsResponse {
	crd_number: string;
	report_date: string | null;
	total_holdings: number;
	holdings: NportHoldingItem[];
	page: number;
	page_size: number;
	total_pages: number;
}

// ── Brochure/Docs tab ──
export interface BrochureSectionItem {
	section: string;
	content_excerpt: string;
	filing_date: string;
}

export interface BrochureSectionsResponse {
	crd_number: string;
	sections: BrochureSectionItem[];
	total_sections: number;
}

export interface BrochureSearchHit {
	section: string;
	headline: string;
	filing_date: string;
	rank: number;
}

export interface BrochureSearchResponse {
	crd_number: string;
	query: string;
	results: BrochureSearchHit[];
	total_results: number;
}

export interface BrochureKeySection {
	section: string;
	content: string;
	filing_date: string | null;
}

export interface ManagerBrochure {
	crd_number: string;
	sections: Record<string, BrochureKeySection>;
}

export const EMPTY_SCREENER: ScreenerPage = {
	managers: [],
	total_count: 0,
	page: 1,
	page_size: 25,
	has_next: false,
};
