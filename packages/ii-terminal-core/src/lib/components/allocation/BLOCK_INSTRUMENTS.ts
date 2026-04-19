/**
 * Static instrument mapping per allocation block.
 * V1: hardcoded. V2: replace with GET /allocation/blocks/{id}/instruments
 * Keys MUST match block_id from /blended-benchmarks/blocks.
 */
import type { BlockInstrument } from "./types";

export const BLOCK_INSTRUMENTS: Record<string, BlockInstrument[]> = {
	na_equity_large: [
		{ ticker: "SPY", name: "iShares S&P 500 ETF", weight: 1.0 },
	],
	na_equity_growth: [
		{ ticker: "QQQ", name: "Invesco QQQ Trust", weight: 1.0 },
	],
	na_equity_value: [
		{ ticker: "IWD", name: "iShares Russell 1000 Value ETF", weight: 1.0 },
	],
	na_equity_small: [
		{ ticker: "IWM", name: "iShares Russell 2000 ETF", weight: 1.0 },
	],
	dm_europe_equity: [
		{ ticker: "VGK", name: "Vanguard FTSE Europe ETF", weight: 1.0 },
	],
	dm_asia_equity: [
		{ ticker: "EWJ", name: "iShares MSCI Japan ETF", weight: 1.0 },
	],
	em_equity: [
		{ ticker: "EEM", name: "iShares MSCI Emerging Markets ETF", weight: 1.0 },
	],
	fi_us_aggregate: [
		{ ticker: "AGG", name: "iShares Core US Aggregate ETF", weight: 1.0 },
	],
	fi_us_treasury: [
		{ ticker: "IEF", name: "iShares 7-10Y Treasury Bond ETF", weight: 1.0 },
	],
	fi_us_tips: [
		{ ticker: "TIP", name: "iShares TIPS Bond ETF", weight: 1.0 },
	],
	fi_us_high_yield: [
		{ ticker: "HYG", name: "iShares iBoxx HY Corp Bond ETF", weight: 1.0 },
	],
	fi_em_debt: [
		{ ticker: "EMB", name: "iShares JPM EM Bond ETF", weight: 1.0 },
	],
	alt_real_estate: [
		{ ticker: "VNQ", name: "Vanguard Real Estate ETF", weight: 1.0 },
	],
	alt_commodities: [
		{ ticker: "DJP", name: "iPath Bloomberg Commodity ETN", weight: 1.0 },
	],
	alt_gold: [
		{ ticker: "GLD", name: "SPDR Gold Shares", weight: 1.0 },
	],
	cash: [
		{ ticker: "SHV", name: "iShares Short Treasury Bond ETF", weight: 1.0 },
	],
};
