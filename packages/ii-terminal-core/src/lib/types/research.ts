export type SignificanceLevel = "high" | "medium" | "low" | "none";

export interface ResearchMetricPoint {
	label: string;
	value: number;
	significance: SignificanceLevel;
}

export interface MarketSensitivitiesPayload {
	exposures: ResearchMetricPoint[];
	r_squared: number | null;
	systematic_risk_pct: number | null;
	as_of_date: string | null;
}

export interface StyleBiasPayload {
	exposures: ResearchMetricPoint[];
	as_of_date: string | null;
}

export interface SingleFundResearchResponse {
	instrument_id: string;
	instrument_name: string;
	ticker: string | null;
	market_sensitivities: MarketSensitivitiesPayload;
	style_bias: StyleBiasPayload;
}

export interface ResearchScatterResponse {
	instrument_ids: string[];
	names: string[];
	tickers: (string | null)[];
	expected_returns: (number | null)[];
	tail_risks: (number | null)[];
	volatilities: (number | null)[];
	strategies: string[];
	strategy_map: Record<string, string>;
	as_of_dates: (string | null)[];
}
