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

// ── UX Glossary — human-readable labels for front-office display ─────
// Intercepts raw DB keys before rendering. Backend stays agnotic.

/** Asset class group names → executive display labels */
export const GROUP_DISPLAY: Record<string, string> = {
	EQUITIES: "Equities",
	"FIXED INCOME": "Fixed Income",
	ALTERNATIVES: "Alternatives",
	"CASH & EQUIVALENTS": "Cash & Equivalents",
	OTHER: "Other Instruments",
};

/** Block IDs → UX-friendly region/sub-class labels (no abbreviations) */
export const BLOCK_DISPLAY: Record<string, string> = {
	na_equity_large: "North America — Large Cap",
	na_equity_growth: "North America — Growth",
	na_equity_value: "North America — Value",
	na_equity_small: "North America — Small Cap",
	dm_europe_equity: "Developed Markets — Europe",
	dm_asia_equity: "Developed Markets — Asia Pacific",
	em_equity: "Emerging Markets",
	fi_us_aggregate: "US Aggregate Bond",
	fi_us_treasury: "US Treasury",
	fi_us_tips: "US Inflation-Protected (TIPS)",
	fi_us_high_yield: "US High Yield",
	fi_em_debt: "Emerging Markets Debt",
	fi_treasury: "Treasuries",
	fi_credit_ig: "Investment Grade Credit",
	fi_credit_hy: "High Yield Credit",
	alt_real_estate: "Real Estate",
	alt_commodities: "Commodities",
	alt_gold: "Gold & Precious Metals",
	alt_reits: "REITs",
	intl_equity_dm: "International — Developed Markets",
	intl_equity_em: "International — Emerging Markets",
	cash: "Cash & Money Market",
};

/** Resolve UX-friendly block display name, fallback to blockLabel */
export function blockDisplay(blockId: string): string {
	return BLOCK_DISPLAY[blockId] ?? blockLabel(blockId);
}

/** Resolve UX-friendly group display name */
export function groupDisplay(groupName: string): string {
	return GROUP_DISPLAY[groupName] ?? groupName;
}

/** Portfolio display name overrides — sanitize aggressive language */
export const PORTFOLIO_DISPLAY: Record<string, string> = {
	"Aggressive Growth": "Strategic Growth",
};

/** Resolve portfolio display name with UX override */
export function portfolioDisplayName(raw: string): string {
	return PORTFOLIO_DISPLAY[raw] ?? raw;
}
