/**
 * Portfolio Workspace — Global state for the unified Portfolio Builder.
 * Manages sidebar/main tab selection, active portfolio, and async operation flags.
 * All API calls go through NetzApiClient (no mocks).
 */

import { createClientApiClient } from "$lib/api/client";
import { BLOCK_LABELS } from "$lib/constants/blocks";
import type {
	ModelPortfolio,
	NAVPoint,
	ParametricStressRequest,
	ParametricStressResult,
	RebalancePreviewRequest,
	RebalancePreviewResponse,
	TrackRecord,
	OverlapResult,
} from "$lib/types/model-portfolio";
import type {
	AttributionResult,
	StrategyDriftAlert,
	CorrelationRegimeResult,
	RiskBudgetResult,
} from "$lib/types/analytics";

// ── Shock mapping: UI macro-shocks → per-block shocks ────────────────
// The backend stress engine expects shocks keyed by allocation block_id.
// We distribute the 3 UI macro-shocks (equity %, rates bps, credit bps)
// to the relevant block IDs using historically-calibrated beta weights.

const EQUITY_BLOCKS: Record<string, number> = {
	na_equity_large: 1.0,
	na_equity_small: 1.2,
	intl_equity_dm: 0.9,
	intl_equity_em: 1.3,
	alt_reits: 0.7,
};

const RATES_BLOCKS: Record<string, number> = {
	fi_treasury: -1.0,
	fi_credit_ig: -0.6,
	fi_credit_hy: -0.3,
	alt_gold: 0.2,
};

const CREDIT_BLOCKS: Record<string, number> = {
	fi_credit_ig: -0.5,
	fi_credit_hy: -1.0,
};

/**
 * Convert UI-level macro shocks to per-block shocks dict.
 * - equity: percentage points (e.g. -20 → -0.20 base)
 * - rates: basis points (e.g. 200 → +0.02 base, i.e. 2% rate move)
 * - credit: basis points (e.g. 150 → +0.015 base, i.e. 1.5% spread move)
 */
export function mapMacroShocksToBlocks(equity: number, rates: number, credit: number): Record<string, number> {
	const shocks: Record<string, number> = {};
	const eqBase = equity / 100;   // -20% → -0.20
	const rtBase = rates / 10000;  // 200bps → 0.02
	const crBase = credit / 10000; // 150bps → 0.015

	for (const [block, beta] of Object.entries(EQUITY_BLOCKS)) {
		shocks[block] = (shocks[block] ?? 0) + eqBase * beta;
	}
	for (const [block, beta] of Object.entries(RATES_BLOCKS)) {
		shocks[block] = (shocks[block] ?? 0) + rtBase * beta;
	}
	for (const [block, beta] of Object.entries(CREDIT_BLOCKS)) {
		shocks[block] = (shocks[block] ?? 0) + crBase * beta;
	}

	// Round to 6 decimal places to avoid floating point noise
	for (const k of Object.keys(shocks)) {
		shocks[k] = Math.round(shocks[k]! * 1e6) / 1e6;
	}

	return shocks;
}

// ── Types ──────────────────────────────────────────────────────────────

export interface StressResultView {
	scenario: string;
	portfolioDrop: number;
	blockImpacts: Record<string, number>;
	cvarStressed: number | null;
	worstBlock: string | null;
	bestBlock: string | null;
}

export interface UniverseFund {
	instrument_id: string;
	fund_name: string;
	ticker: string | null;
	block_id: string;
	block_label: string;
	asset_class: string | null;
	geography: string | null;
	instrument_type: string;
	manager_score: number | null;
	/** Pre-computed lowercase search key: "name|ticker|block_label" */
	_searchKey: string;
}

/** Raw shape from GET /universe (matches UniverseAssetRead). */
interface UniverseApiItem {
	instrument_id: string;
	fund_name: string;
	ticker: string | null;
	block_id: string | null;
	asset_class: string | null;
	geography: string | null;
	approval_status: string | null;
	manager_score: number | null;
}

export interface WorkspaceError {
	action: string;
	message: string;
	timestamp: number;
}

export interface FactorContribution {
	factor_label: string;
	pct_contribution: number;
}

export interface FactorAnalysisResponse {
	profile: string;
	as_of_date: string;
	systematic_risk_pct: number;
	specific_risk_pct: number;
	factor_contributions: FactorContribution[];
	r_squared: number;
	portfolio_factor_exposures: Record<string, number>;
}

export class PortfolioWorkspaceState {
	/** Builder sub-pills: Models | Universe | Policy */
	activeBuilderTab = $state<"models" | "universe" | "policy">("models");
	/** Model detail sub-pills: Holdings | Factor Analysis | Stress Testing | Overlap | Rebalance */
	activeModelTab = $state<"overview" | "factor" | "stress" | "overlap" | "rebalance">("overview");
	/** Analytics sub-pills: Attribution | Factor | Drift | Risk Budget */
	activeAnalyticsTab = $state<"attribution" | "factor" | "drift" | "risk-budget">("attribution");
	portfolio = $state<ModelPortfolio | null>(null);
	localStress = $state.raw<StressResultView | null>(null);
	localFactorAnalysis = $state.raw<FactorAnalysisResponse | null>(null);
	localOverlap = $state.raw<OverlapResult | null>(null);
	/** Synthesized NAV series from backend track-record endpoint. */
	navSeries = $state<NAVPoint[]>([]);
	isLoadingTrackRecord = $state(false);
	isLoadingFactorAnalysis = $state(false);
	isLoadingOverlap = $state(false);
	isConstructing = $state(false);
	isStressing = $state(false);
	isRebalancing = $state(false);
	isExecuting = $state(false);
	rebalanceResult = $state.raw<RebalancePreviewResponse | null>(null);
	lastError = $state.raw<WorkspaceError | null>(null);

	/** Attribution analysis (Brinson-Fachler) for current portfolio profile. */
	attribution = $state.raw<AttributionResult | null>(null);
	isLoadingAttribution = $state(false);

	/** Strategy drift alerts across instruments. */
	driftAlerts = $state.raw<StrategyDriftAlert[]>([]);
	isLoadingDrift = $state(false);

	/** Correlation regime analysis (Marchenko-Pastur denoising). */
	correlationRegime = $state.raw<CorrelationRegimeResult | null>(null);
	isLoadingCorrelationRegime = $state(false);

	/** Risk budget decomposition (on-demand). */
	riskBudget = $state.raw<RiskBudgetResult | null>(null);
	isLoadingRiskBudget = $state(false);

	/** Approved universe funds for DnD — loaded from API when portfolio is selected. */
	universe = $state<UniverseFund[]>([]);

	/** Token provider — set once from +page.svelte via setGetToken(). */
	private _getToken: (() => Promise<string>) | null = null;

	portfolioId = $derived(this.portfolio?.id ?? null);
	funds = $derived(this.portfolio?.fund_selection_schema?.funds ?? []);

	/** Sum of all fund weights across all blocks (should be ~1.0 after construction). */
	totalWeight = $derived(this.funds.reduce((sum, f) => sum + (f.weight ?? 0), 0));

	/** True when total weight is outside the acceptable [0.98, 1.02] range. */
	weightWarning = $derived(this.funds.length > 0 && (this.totalWeight < 0.98 || this.totalWeight > 1.02));

	/** Group current funds by block_id for drop-zone rendering */
	fundsByBlock = $derived.by(() => {
		const map: Record<string, any[]> = {};
		for (const f of this.funds) {
			(map[f.block_id] ??= []).push(f);
		}
		return map;
	});

	/** All distinct block IDs present in the portfolio */
	activeBlocks = $derived(Object.keys(this.fundsByBlock));

	setGetToken(fn: () => Promise<string>) {
		this._getToken = fn;
	}

	private api() {
		if (!this._getToken) throw new Error("Token provider not configured");
		return createClientApiClient(this._getToken);
	}

	selectPortfolio(p: ModelPortfolio) {
		this.portfolio = p;
		this.localStress = null;
		this.localFactorAnalysis = null;
		this.localOverlap = null;
		this.rebalanceResult = null;
		this.attribution = null;
		this.driftAlerts = [];
		this.correlationRegime = null;
		this.riskBudget = null;
		this.lastError = null;
		this.navSeries = [];
		// Fire-and-forget: load track-record, factor analysis, attribution, drift
		this.loadTrackRecord();
		this.loadDriftAlerts();

		if (p.profile) {
			this.loadFactorAnalysis(p.profile);
			this.loadAttribution(p.profile);
			// Correlation regime requires constructed portfolio with fund data
			if (p.fund_selection_schema?.funds?.length) {
				this.loadCorrelationRegime(p.profile);
			}
		}
		if (p.id) {
			this.loadOverlap();
		}
	}

	// ── Track-record loading (real API) ─────────────────────────────

	/** Fetch synthesized NAV series from GET /model-portfolios/{id}/track-record. */
	async loadTrackRecord() {
		if (!this._getToken || !this.portfolioId) return;
		this.isLoadingTrackRecord = true;

		try {
			const api = this.api();
			const result = await api.get<TrackRecord>(
				`/model-portfolios/${this.portfolioId}/track-record`,
			);
			this.navSeries = result.nav_series ?? [];
		} catch (err) {
			this.lastError = {
				action: "track-record",
				message: err instanceof Error ? err.message : "Failed to load track record",
				timestamp: Date.now(),
			};
			this.navSeries = [];
		} finally {
			this.isLoadingTrackRecord = false;
		}
	}

	async loadFactorAnalysis(profile: string) {
		this.isLoadingFactorAnalysis = true;
		try {
			const api = this.api();
			const result = await api.get<FactorAnalysisResponse>(
				`/analytics/factor-analysis/${profile}`
			);
			this.localFactorAnalysis = result;
			this.lastError = null;
		} catch (err: any) {
			console.error("loadFactorAnalysis error:", err);
			this.lastError = {
				action: "factor-analysis",
				message: err.message || "Unknown error resolving factor analysis",
				timestamp: Date.now()
			};
		} finally {
			this.isLoadingFactorAnalysis = false;
		}
	}

	// ── Overlap loading (real API) ──────────────────────────────────

	async loadOverlap() {
		if (!this._getToken || !this.portfolioId) return;
		this.isLoadingOverlap = true;
		try {
			const api = this.api();
			const result = await api.get<OverlapResult>(
				`/model-portfolios/${this.portfolioId}/overlap`
			);
			this.localOverlap = result;
		} catch (err: any) {
			console.error("loadOverlap error:", err);
			this.lastError = {
				action: "overlap",
				message: err.message || "Unknown error fetching overlaps",
				timestamp: Date.now()
			};
			this.localOverlap = null;
		} finally {
			this.isLoadingOverlap = false;
		}
	}

	// ── Attribution loading (Brinson-Fachler) ───────────────────────

	async loadAttribution(profile: string) {
		if (!this._getToken) return;
		this.isLoadingAttribution = true;
		try {
			const api = this.api();
			this.attribution = await api.get<AttributionResult>(
				`/analytics/attribution/${profile}`,
			);
		} catch {
			this.attribution = null;
		} finally {
			this.isLoadingAttribution = false;
		}
	}

	// ── Drift alerts loading ────────────────────────────────────────

	async loadDriftAlerts() {
		if (!this._getToken) return;
		this.isLoadingDrift = true;
		try {
			const api = this.api();
			this.driftAlerts = await api.get<StrategyDriftAlert[]>(
				"/analytics/strategy-drift/alerts",
				{ limit: "50" },
			);
		} catch {
			this.driftAlerts = [];
		} finally {
			this.isLoadingDrift = false;
		}
	}

	// ── Correlation regime loading ──────────────────────────────────

	async loadCorrelationRegime(profile: string) {
		if (!this._getToken) return;
		this.isLoadingCorrelationRegime = true;
		try {
			const api = this.api();
			this.correlationRegime = await api.get<CorrelationRegimeResult>(
				`/analytics/correlation-regime/${profile}`,
				{ window_days: "60" },
			);
		} catch {
			this.correlationRegime = null;
		} finally {
			this.isLoadingCorrelationRegime = false;
		}
	}

	// ── Risk budget loading (on-demand) ─────────────────────────────

	async loadRiskBudget() {
		if (!this._getToken || !this.portfolio?.profile) return;
		this.isLoadingRiskBudget = true;
		try {
			const api = this.api();
			this.riskBudget = await api.post<RiskBudgetResult>(
				`/analytics/risk-budget/${this.portfolio.profile}`,
				{},
			);
		} catch {
			this.riskBudget = null;
		} finally {
			this.isLoadingRiskBudget = false;
		}
	}

	// ── Universe loading (real API) ──────────────────────────────────

	/** True while universe is being fetched from API. */
	isLoadingUniverse = $state(false);

	/** Load approved universe funds from GET /universe. */
	async loadUniverse() {
		if (!this._getToken) return;
		this.isLoadingUniverse = true;

		try {
			const api = this.api();
			const result = await api.get<UniverseApiItem[]>("/universe");

			this.universe = result.map((r) => {
				const blockId = r.block_id ?? "unknown";
				const label = BLOCK_LABELS[blockId] ?? blockId.replace(/_/g, " ");
				const name = r.fund_name.toLowerCase();
				const ticker = (r.ticker ?? "").toLowerCase();
				return {
					instrument_id: r.instrument_id,
					fund_name: r.fund_name,
					ticker: r.ticker ?? null,
					block_id: blockId,
					block_label: label,
					asset_class: r.asset_class ?? null,
					geography: r.geography ?? null,
					instrument_type: r.asset_class ?? "fund",
					manager_score: r.manager_score ?? null,
					_searchKey: `${name}|${ticker}|${label.toLowerCase()}`,
				};
			});
		} catch (err) {
			this.lastError = {
				action: "universe",
				message: err instanceof Error ? err.message : "Failed to load universe",
				timestamp: Date.now(),
			};
			this.universe = [];
		} finally {
			this.isLoadingUniverse = false;
		}
	}

	/**
	 * Add a fund from the universe into a specific allocation block.
	 * Rejects if the fund's block_id doesn't match the target block.
	 * Recalculates equal weights within the block after insertion.
	 */
	addFundToBlock(fund: UniverseFund, blockId: string): boolean {
		if (!this.portfolio) return false;
		if (fund.block_id !== blockId) return false;

		// Initialize schema if missing
		if (!this.portfolio.fund_selection_schema) {
			this.portfolio = {
				...this.portfolio,
				fund_selection_schema: { profile: this.portfolio.profile, total_weight: 0, funds: [] },
			};
		}
		const schema = this.portfolio.fund_selection_schema!;
		if (!schema.funds) schema.funds = [];

		// Reject duplicates
		if (schema.funds.some((f) => f.instrument_id === fund.instrument_id)) return false;

		// Add with temporary weight 0
		schema.funds.push({
			instrument_id: fund.instrument_id,
			fund_name: fund.fund_name,
			block_id: fund.block_id,
			instrument_type: fund.instrument_type as any,
			score: 0,
			weight: 0,
		});

		// Recalculate equal weights within this block
		const blockFunds = schema.funds.filter((f) => f.block_id === blockId);
		const equalWeight = Math.round((1 / blockFunds.length) * 10000) / 10000;
		for (const f of blockFunds) {
			f.weight = equalWeight;
		}

		// Trigger reactivity
		this.portfolio = { ...this.portfolio };
		return true;
	}

	updatePolicy(key: "cvar_limit" | "max_single_fund_weight", value: number) {
		if (!this.portfolio) return;
		// Policy updates are local UI state — the backend reads policy from StrategicAllocation table
		this.portfolio = { ...this.portfolio };
	}

	// ── Construction & Live Rebalance ─────────────────────────────────────────

	async constructPortfolio() {
		if (!this.portfolioId) return;
		this.isConstructing = true;
		this.lastError = null;

		try {
			const api = this.api();
			// POST /model-portfolios/{id}/construct — no body required.
			// Backend reads approved universe + strategic allocation from DB.
			// Timeout extended: CLARABEL optimizer can take 10-30s.
			const result = await api.post<ModelPortfolio>(
				`/model-portfolios/${this.portfolioId}/construct`,
				undefined,
				{ timeoutMs: 60_000 },
			);

			// Update local state with the full portfolio returned (includes fund_selection_schema)
			this.portfolio = result;
		} catch (err) {
			this.lastError = {
				action: "construct",
				message: err instanceof Error ? err.message : "Construction failed",
				timestamp: Date.now(),
			};
		} finally {
			this.isConstructing = false;
		}
	}

	// ── Rebalance Preview (real API) ─────────────────────────────────

	async runRebalancePreview(payload: RebalancePreviewRequest) {
		if (!this.portfolioId) return;
		this.isRebalancing = true;
		this.lastError = null;

		try {
			const api = this.api();
			const result = await api.post<RebalancePreviewResponse>(
				`/model-portfolios/${this.portfolioId}/rebalance/preview`,
				payload,
				{ timeoutMs: 30_000 },
			);
			this.rebalanceResult = result;
		} catch (err) {
			this.lastError = {
				action: "rebalance",
				message: err instanceof Error ? err.message : "Rebalance preview failed",
				timestamp: Date.now(),
			};
		} finally {
			this.isRebalancing = false;
		}
	}

	async executeTrades(payload: RebalancePreviewRequest) {
		if (!this.portfolioId) return;
		this.isExecuting = true;
		this.lastError = null;

		try {
			const api = this.api();
			// POST /model-portfolios/{id}/rebalance/execute 
			await api.post(
				`/model-portfolios/${this.portfolioId}/rebalance/execute`,
				payload,
				{ timeoutMs: 30_000 },
			);
		} catch (err) {
			this.lastError = {
				action: "execute-trades",
				message: err instanceof Error ? err.message : "Trade execution failed",
				timestamp: Date.now(),
			};
			throw err;
		} finally {
			this.isExecuting = false;
		}
	}

	// ── Parametric Stress Test (real API) ─────────────────────────────

	async runStressTest(shocks: { equity: number; rates: number; credit: number }) {
		if (!this.portfolioId) return;
		this.isStressing = true;
		this.lastError = null;

		try {
			const api = this.api();

			// Map UI macro-shocks to per-block shocks (with unit conversion)
			const blockShocks = mapMacroShocksToBlocks(shocks.equity, shocks.rates, shocks.credit);

			const body: ParametricStressRequest = {
				scenario_name: "custom",
				shocks: blockShocks,
			};

			const result = await api.post<ParametricStressResult>(
				`/model-portfolios/${this.portfolioId}/stress-test`,
				body,
				{ timeoutMs: 30_000 },
			);

			// Convert API response (decimals) to view model (percentages for display)
			this.localStress = {
				scenario: result.scenario_name,
				portfolioDrop: result.nav_impact_pct * 100,
				blockImpacts: Object.fromEntries(
					Object.entries(result.block_impacts).map(([k, v]) => [k, v * 100]),
				),
				cvarStressed: result.cvar_stressed,
				worstBlock: result.worst_block,
				bestBlock: result.best_block,
			};
		} catch (err) {
			this.lastError = {
				action: "stress",
				message: err instanceof Error ? err.message : "Stress test failed",
				timestamp: Date.now(),
			};
		} finally {
			this.isStressing = false;
		}
	}
}

export const workspace = new PortfolioWorkspaceState();
