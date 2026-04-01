/** Block display labels — single source of truth for all allocation block IDs. */

export const BLOCK_LABELS: Record<string, string> = {
	na_equity_large: "NA Equity Large",
	na_equity_growth: "NA Equity Growth",
	na_equity_value: "NA Equity Value",
	na_equity_small: "NA Equity Small",
	dm_europe_equity: "DM Europe Equity",
	dm_asia_equity: "DM Asia Equity",
	em_equity: "Emerging Markets Equity",
	fi_us_aggregate: "FI US Aggregate",
	fi_us_treasury: "FI US Treasury",
	fi_us_tips: "FI US TIPS",
	fi_us_high_yield: "FI US High Yield",
	fi_em_debt: "FI EM Debt",
	fi_treasury: "Treasuries",
	fi_credit_ig: "Credit IG",
	fi_credit_hy: "Credit HY",
	alt_real_estate: "Alt Real Estate",
	alt_commodities: "Alt Commodities",
	alt_gold: "Alt Gold",
	alt_reits: "REITs",
	intl_equity_dm: "Intl Equity DM",
	intl_equity_em: "Intl Equity EM",
	cash: "Cash",
};

export function blockLabel(blockId: string): string {
	return BLOCK_LABELS[blockId] ?? blockId.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export const BLOCK_GROUPS: Record<string, string[]> = {
	EQUITIES: ["na_equity_large", "na_equity_growth", "na_equity_value", "na_equity_small", "dm_europe_equity", "dm_asia_equity", "em_equity"],
	"FIXED INCOME": ["fi_us_aggregate", "fi_us_treasury", "fi_us_tips", "fi_us_high_yield", "fi_em_debt"],
	ALTERNATIVES: ["alt_real_estate", "alt_commodities", "alt_gold"],
	"CASH & EQUIVALENTS": ["cash"],
};
