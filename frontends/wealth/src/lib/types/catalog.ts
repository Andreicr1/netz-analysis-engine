/** Unified Fund Catalog types — maps 1:1 to backend schemas/catalog.py. */

export interface DisclosureMatrix {
	has_holdings: boolean;
	has_nav_history: boolean;
	has_quant_metrics: boolean;
	has_private_fund_data: boolean;
	has_style_analysis: boolean;
	has_13f_overlay: boolean;
	has_peer_analysis: boolean;
	holdings_source: "nport" | "13f" | null;
	nav_source: "yfinance" | null;
	aum_source: "nport" | "schedule_d" | "yfinance" | null;
}

export type FundUniverse = "registered_us" | "private_us" | "ucits_eu";
export type FundRegion = "US" | "EU";

export interface UnifiedFundItem {
	external_id: string;
	universe: FundUniverse;
	name: string;
	ticker: string | null;
	isin: string | null;

	region: FundRegion;
	fund_type: string;
	domicile: string | null;
	currency: string | null;

	manager_name: string | null;
	manager_id: string | null;

	aum: number | null;
	inception_date: string | null;
	total_shareholder_accounts: number | null;
	investor_count: number | null;

	// Share class fields (populated for registered_us funds with classes)
	series_id: string | null;
	series_name: string | null;
	class_id: string | null;
	class_name: string | null;

	instrument_id: string | null;
	screening_status: "PASS" | "FAIL" | "WATCHLIST" | null;
	screening_score: number | null;
	approval_status: string | null;

	disclosure: DisclosureMatrix;
}

export interface CatalogFacetItem {
	value: string;
	label: string;
	count: number;
}

export interface CatalogFacets {
	universes: CatalogFacetItem[];
	regions: CatalogFacetItem[];
	fund_types: CatalogFacetItem[];
	domiciles: CatalogFacetItem[];
	total: number;
}

export interface UnifiedCatalogPage {
	items: UnifiedFundItem[];
	total: number;
	page: number;
	page_size: number;
	has_next: boolean;
	facets: CatalogFacets | null;
}

export const EMPTY_CATALOG_PAGE: UnifiedCatalogPage = {
	items: [],
	total: 0,
	page: 1,
	page_size: 50,
	has_next: false,
	facets: null,
};

export const EMPTY_FACETS: CatalogFacets = {
	universes: [],
	regions: [],
	fund_types: [],
	domiciles: [],
	total: 0,
};

export const UNIVERSE_LABELS: Record<FundUniverse, string> = {
	registered_us: "US Registered",
	private_us: "US Private",
	ucits_eu: "EU UCITS",
};

export const REGION_LABELS: Record<FundRegion, string> = {
	US: "United States",
	EU: "European Union",
};

// ── Global Securities (equities/ETFs from sec_cusip_ticker_map — no RLS) ──

export interface SecurityItem {
	cusip: string;
	ticker: string | null;
	name: string;
	security_type: string;
	exchange: string | null;
	asset_class: string;
	figi: string | null;
	is_tradeable: boolean;
}

export interface SecurityPage {
	items: SecurityItem[];
	total: number;
	page: number;
	page_size: number;
	has_next: boolean;
}

export interface SecurityFacets {
	security_types: CatalogFacetItem[];
	exchanges: CatalogFacetItem[];
	total: number;
}

export const EMPTY_SECURITY_PAGE: SecurityPage = {
	items: [],
	total: 0,
	page: 1,
	page_size: 50,
	has_next: false,
};

export const EMPTY_SECURITY_FACETS: SecurityFacets = {
	security_types: [],
	exchanges: [],
	total: 0,
};
