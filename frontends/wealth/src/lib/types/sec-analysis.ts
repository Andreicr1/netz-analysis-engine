/** SEC Analysis domain types — US Fund Analysis page. */

export interface SecManagerItem {
	crd_number: string;
	cik: string | null;
	firm_name: string;
	registration_status: string | null;
	aum_total: number | null;
	state: string | null;
	country: string | null;
	sic: string | null;
	sic_description: string | null;
	last_adv_filed_at: string | null;
	compliance_disclosures: number | null;
}

export interface SecManagerSearchPage {
	managers: SecManagerItem[];
	total_count: number;
	page: number;
	page_size: number;
	has_next: boolean;
}

export interface SecManagerDetail {
	crd_number: string;
	cik: string | null;
	firm_name: string;
	registration_status: string | null;
	aum_total: number | null;
	state: string | null;
	country: string | null;
	website: string | null;
	sic: string | null;
	sic_description: string | null;
	last_adv_filed_at: string | null;
	latest_quarter: string | null;
	holdings_count: number;
	total_portfolio_value: number | null;
}

export interface SecHoldingItem {
	cusip: string;
	company_name: string;
	sector: string | null;
	shares: number | null;
	market_value: number | null;
	pct_portfolio: number | null;
	delta_shares: number | null;
	delta_value: number | null;
	delta_action: string | null;
}

export interface SecHoldingsPage {
	cik: string;
	quarter: string | null;
	available_quarters: string[];
	holdings: SecHoldingItem[];
	total_count: number;
	total_value: number | null;
	page: number;
	page_size: number;
	has_next: boolean;
}

export interface SectorWeight {
	quarter: string;
	sector: string;
	weight_pct: number;
}

export interface StyleDriftSignal {
	sector: string;
	weight_current: number;
	weight_prev: number;
	delta: number;
	signal: string;
}

export interface SecStyleDrift {
	cik: string;
	history: SectorWeight[];
	drift_signals: StyleDriftSignal[];
}

export interface ReverseLookupItem {
	cik: string;
	firm_name: string;
	shares: number | null;
	market_value: number | null;
	pct_of_total: number | null;
	report_date: string;
}

export interface SecReverseLookup {
	cusip: string;
	company_name: string | null;
	holders: ReverseLookupItem[];
	total_holders: number;
}

export interface PeerHoldingOverlap {
	cik_a: string;
	cik_b: string;
	overlap_pct: number;
}

export interface SecPeerCompare {
	managers: SecManagerDetail[];
	sector_allocations: Record<string, Record<string, number>>;
	overlaps: PeerHoldingOverlap[];
	hhi_scores: Record<string, number>;
	fund_breakdowns: Record<string, SecManagerFundBreakdown>;
}

export interface SecManagerFundItem {
	fund_type: string;
	fund_count: number;
	pct_of_total: number;
}

export interface SecManagerFundBreakdown {
	crd_number: string;
	total_funds: number;
	breakdown: SecManagerFundItem[];
}

export interface SecSicCodeItem {
	sic: string;
	sic_description: string | null;
	count: number;
}

export interface SecHoldingsHistoryPoint {
	quarter: string;
	total_holders: number;
	total_market_value: number;
}

export interface SecHoldingsHistory {
	cusip: string;
	quarters: SecHoldingsHistoryPoint[];
}

export const EMPTY_SEARCH_PAGE: SecManagerSearchPage = {
	managers: [],
	total_count: 0,
	page: 1,
	page_size: 25,
	has_next: false,
};

export const EMPTY_HOLDINGS: SecHoldingsPage = {
	cik: "",
	quarter: null,
	available_quarters: [],
	holdings: [],
	total_count: 0,
	total_value: null,
	page: 1,
	page_size: 50,
	has_next: false,
};

export const EMPTY_STYLE_DRIFT: SecStyleDrift = {
	cik: "",
	history: [],
	drift_signals: [],
};

export const EMPTY_REVERSE: SecReverseLookup = {
	cusip: "",
	company_name: null,
	holders: [],
	total_holders: 0,
};
