/** Screening domain types — maps 1:1 to backend schemas. */

export interface CriterionResult {
	criterion: string;
	expected: string;
	actual: string;
	passed: boolean;
	layer: number;
}

export interface ScreeningResult {
	id: string;
	instrument_id: string;
	run_id: string;
	overall_status: "PASS" | "FAIL" | "WATCHLIST";
	score: number | null;
	failed_at_layer: number | null;
	layer_results: CriterionResult[];
	required_analysis_type: "dd_report" | "bond_brief" | "none";
	screened_at: string;
	is_current: boolean;
	/** Joined from instruments_universe */
	name?: string;
	isin?: string;
	ticker?: string;
	instrument_type?: string;
	block_id?: string | null;
	manager?: string;
	manager_crd?: string | null;
	geography?: string;
	strategy?: string;
	aum?: number | null;
	currency?: string;
}

export interface ScreeningRun {
	run_id: string;
	instrument_count: number;
	started_at: string;
	completed_at: string | null;
	status: "running" | "completed";
}

export type OverallStatus = "PASS" | "FAIL" | "WATCHLIST";

export interface ScreenerFilterConfig {
	status: OverallStatus | null;
	instrument_type: string | null;
	block_id: string | null;
	search: string;
}

export const EMPTY_FILTERS: ScreenerFilterConfig = {
	status: null,
	instrument_type: null,
	block_id: null,
	search: "",
};

// ── Source display labels (never expose data-provider names to users) ───
export const SOURCE_LABELS: Record<string, string> = {
	internal: "Universe",
	esma: "UCITS",
	sec: "US Registered",
};

// ── Global Instrument Search types ──────────────────────────────────────

export interface InstrumentSearchItem {
	instrument_id: string | null;
	source: "internal" | "esma" | "sec";
	instrument_type: "fund" | "bond" | "equity" | "etf" | "hedge_fund";
	name: string;
	isin: string | null;
	ticker: string | null;
	asset_class: string;
	geography: string;
	domicile: string | null;
	currency: string;
	strategy: string | null;
	aum: number | null;
	manager_name: string | null;
	manager_crd: string | null;
	esma_manager_id: string | null;
	approval_status: string | null;
	screening_status: "PASS" | "FAIL" | "WATCHLIST" | null;
	screening_score: number | null;
	nav_1y_return: number | null;
	nav_3m_return: number | null;
	block_id: string | null;
	structure: string | null;
}

export interface InstrumentSearchPage {
	items: InstrumentSearchItem[];
	total: number;
	page: number;
	page_size: number;
	has_next: boolean;
}

export interface FacetItem {
	value: string;
	label: string;
	count: number;
}

export type ScreenerTab = "fund" | "equity" | "bond" | "etf" | "instruments" | "managers";

export interface ScreenerFacets {
	instrument_types: FacetItem[];
	geographies: FacetItem[];
	asset_classes: FacetItem[];
	domiciles: FacetItem[];
	currencies: FacetItem[];
	strategies: FacetItem[];
	sources: FacetItem[];
	screening_statuses: FacetItem[];
	sectors: FacetItem[];
	exchanges: FacetItem[];
	total_universe: number;
	total_screened: number;
	total_approved: number;
}

export const EMPTY_SEARCH_PAGE: InstrumentSearchPage = {
	items: [],
	total: 0,
	page: 1,
	page_size: 50,
	has_next: false,
};

export const EMPTY_FACETS: ScreenerFacets = {
	instrument_types: [],
	geographies: [],
	asset_classes: [],
	domiciles: [],
	currencies: [],
	strategies: [],
	sources: [],
	screening_statuses: [],
	sectors: [],
	exchanges: [],
	total_universe: 0,
	total_screened: 0,
	total_approved: 0,
};
