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
	ConstructionAdvice,
} from "$lib/types/model-portfolio";
import type {
	AttributionResult,
	StrategyDriftAlert,
	CorrelationRegimeResult,
	RiskBudgetResult,
} from "$lib/types/analytics";
import type {
	PortfolioCalibration,
	PortfolioCalibrationUpdate,
} from "$lib/types/portfolio-calibration";

/**
 * Phase 3 Run Construct response payload — flat dict returned from
 * ``GET /model-portfolios/{portfolio_id}/runs/{run_id}``. Every field
 * maps to a column on ``portfolio_construction_runs`` (DL4). Consumed
 * by the ConstructionNarrative + Stress matrix components in Phase 4.
 */
export interface ConstructionRunPayload {
	run_id: string;
	portfolio_id: string;
	status: "running" | "succeeded" | "failed" | "superseded";
	as_of_date: string;
	requested_by: string;
	requested_at: string | null;
	started_at: string | null;
	completed_at: string | null;
	wall_clock_ms: number | null;
	failure_reason: string | null;
	calibration_snapshot: Record<string, unknown> | null;
	optimizer_trace: Record<string, unknown> | null;
	binding_constraints: unknown;
	regime_context: Record<string, unknown> | null;
	statistical_inputs: Record<string, unknown> | null;
	ex_ante_metrics: Record<string, number | null> | null;
	ex_ante_vs_previous: Record<string, number | null> | null;
	factor_exposure: Record<string, unknown> | null;
	stress_results: ConstructionStressResult[] | null;
	advisor: Record<string, unknown> | null;
	validation: ConstructionValidationResult | null;
	narrative: ConstructionNarrativeContent | null;
	rationale_per_weight: Record<string, unknown> | null;
	weights_proposed: Record<string, number> | null;
}

export interface ConstructionStressResult {
	scenario: string;
	scenario_kind: "preset" | "user_defined";
	nav_impact_pct: number | null;
	cvar_impact_pct: number | null;
	per_block_impact: Record<string, number> | null;
	per_instrument_impact: Record<string, number> | null;
}

export interface ConstructionValidationCheck {
	id: string;
	label: string;
	severity: "block" | "warn";
	passed: boolean;
	value: number | null;
	threshold: number | null;
	explanation: string;
}

export interface ConstructionValidationResult {
	passed: boolean;
	checks: ConstructionValidationCheck[];
	warnings: ConstructionValidationCheck[];
}

export interface ConstructionNarrativeContent {
	headline?: string;
	key_points?: string[];
	constraint_story?: string;
	holding_changes?: Array<{
		instrument_id: string;
		name: string;
		prev_weight: number | null;
		next_weight: number;
		delta: number;
	}>;
	client_safe?: string;
}

/** Phase 3 Job-or-Stream 202 response from POST /{id}/construct. */
export interface ConstructRunAccepted {
	run_id: string;
	portfolio_id: string;
	status: "running" | "succeeded" | "failed" | "cached";
	job_id: string;
	stream_url: string;
	run_url: string;
}

/**
 * SSE event shape emitted by the ``construction_run_executor``.
 * ``event`` is the type discriminator; the remaining keys are the
 * event-specific payload.
 */
export interface ConstructRunEvent {
	event:
		| "run_started"
		| "optimizer_started"
		| "stress_started"
		| "done"
		| "error";
	run_id?: string;
	portfolio_id?: string;
	status?: string;
	wall_clock_ms?: number;
	reason?: string;
}

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
	/**
	 * Tier 1 density fields (Flexible Columns Layout spec §3.1).
	 * Populated from fund_risk_metrics + nav_timeseries + correlation
	 * service. `null` means the metric is not yet computed for this
	 * instrument — the UI renders em-dash, never crashes.
	 */
	aum_usd: number | null;
	expense_ratio: number | null;
	return_3y_ann: number | null;
	sharpe_1y: number | null;
	max_drawdown_1y: number | null;
	blended_momentum_score: number | null;
	liquidity_tier: string | null;
	correlation_to_portfolio: number | null;
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
	aum_usd: number | null;
	expense_ratio: number | null;
	return_3y_ann: number | null;
	sharpe_1y: number | null;
	max_drawdown_1y: number | null;
	blended_momentum_score: number | null;
	liquidity_tier: string | null;
	correlation_to_portfolio: number | null;
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
	/** Model detail sub-pills: Holdings | Factor Analysis | Stress Testing | Overlap | Rebalance | Reporting */
	activeModelTab = $state<"overview" | "factor" | "stress" | "overlap" | "rebalance" | "reporting">("overview");
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
	isLoadingAdvice = $state(false);
	advice = $state.raw<ConstructionAdvice | null>(null);
	/** True after a fetchConstructionAdvice() attempt (success or failure) for the current portfolio. Reset on selectPortfolio(). */
	adviceFetched = $state(false);
	isActivating = $state(false);
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

	// ── Phase 4 — Calibration + Construction Narrative ────────────────
	/**
	 * Tiered calibration surface (DL5). Loaded on selectPortfolio().
	 * The Builder's CalibrationPanel reads this as the source-of-truth
	 * snapshot; editing happens in a local ``draft`` owned by the
	 * panel and persisted via ``applyCalibration`` on Apply.
	 */
	calibration = $state.raw<PortfolioCalibration | null>(null);
	isLoadingCalibration = $state(false);
	isApplyingCalibration = $state(false);

	/**
	 * Phase 3 construct run payload for the current portfolio — loaded
	 * either after a successful ``runConstructJob`` (via the SSE stream
	 * terminal ``done`` event) or on-demand via ``loadConstructionRun``.
	 * Empty means "no run yet" — ConstructionNarrative renders the
	 * institutional empty state (DL4 + OD-26 strict).
	 */
	constructionRun = $state.raw<ConstructionRunPayload | null>(null);
	isLoadingRun = $state(false);

	/**
	 * Run Construct SSE state — replaces the legacy ``isConstructing``
	 * boolean. ``runPhase`` advances as the executor publishes events:
	 *
	 *   idle → running → optimizer → stress → done (or error)
	 *
	 * Phase 4 Task 4.5 Job-or-Stream wiring (DL18 P2). Consumed by
	 * BuilderColumn / BuilderRightStack for the "Building…" pill + the
	 * auto-switch to the Narrative tab on ``done``.
	 */
	runPhase = $state<"idle" | "running" | "optimizer" | "stress" | "done" | "error">("idle");
	runError = $state<string | null>(null);
	private _activeRunAbort: AbortController | null = null;

	/** Approved universe funds for DnD — loaded from API when portfolio is selected. */
	universe = $state<UniverseFund[]>([]);

	/**
	 * Analytics column mode — drives Estado C of the Flexible Columns
	 * Layout (design spec 2026-04-08). Three mutually-exclusive modes:
	 *
	 *   - `"fund"` → PM clicked a row in the Universe table; the 3rd
	 *     column shows the drill-down for `selectedAnalyticsFund`.
	 *   - `"portfolio"` → PM clicked "View Chart" in the Builder
	 *     action bar; the 3rd column shows MainPortfolioChart (NAV
	 *     synthesis) for the current portfolio. This was previously
	 *     pinned to the top of the Builder column — moved here so
	 *     the Builder has full vertical space for allocation blocks.
	 *   - `null` → Estado B (2 columns only, 3rd column hidden).
	 *
	 * Reset rules:
	 *   1. Cleared on `selectPortfolio()` (switching model starts fresh).
	 *   2. Cleared on `resetBuilderEntry()` (re-entering /portfolio from
	 *      another route — "reset ao voltar" rule).
	 *   3. Cleared directly by the Analytics close button via
	 *      `clearAnalytics()`.
	 *
	 * NOT armazenado como `layoutState`. The layout state is derived:
	 *   analyticsMode !== null ? "three-col" : "two-col"
	 */
	analyticsMode = $state.raw<"fund" | "portfolio" | null>(null);

	/**
	 * The specific fund populating the Analytics column when
	 * `analyticsMode === "fund"`. Ignored in `"portfolio"` mode.
	 */
	selectedAnalyticsFund = $state.raw<UniverseFund | null>(null);

	/** Token provider — set once from +page.svelte via setGetToken(). */
	private _getToken: (() => Promise<string>) | null = null;

	/**
	 * Generation counter — incremented on every selectPortfolio() call.
	 * Async methods capture the value at start and bail if it changed,
	 * preventing stale responses from overwriting current portfolio data.
	 */
	private _generation = 0;

	portfolioId = $derived(this.portfolio?.id ?? null);
	funds = $derived(this.portfolio?.fund_selection_schema?.funds ?? []);

	/** Sum of all fund weights across all blocks (should be ~1.0 after construction). */
	totalWeight = $derived(this.funds.reduce((sum, f) => sum + (f.weight ?? 0), 0));

	/** True when total weight is outside the acceptable [0.98, 1.02] range. */
	weightWarning = $derived(this.funds.length > 0 && (this.totalWeight < 0.98 || this.totalWeight > 1.02));

	/** Optimizer metadata from the last construction result (if available). */
	optimizationMeta = $derived(this.portfolio?.fund_selection_schema?.optimization ?? null);

	/** True when the last construction violated the CVaR risk limit. */
	cvarViolated = $derived(this.optimizationMeta?.cvar_within_limit === false);

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

	/**
	 * Open the Analytics column in "fund" mode with the given fund.
	 * Triggered by a row click in the Universe table.
	 */
	openAnalyticsForFund(fund: UniverseFund) {
		this.selectedAnalyticsFund = fund;
		this.analyticsMode = "fund";
	}

	/**
	 * Open the Analytics column in "portfolio" mode showing the
	 * MainPortfolioChart NAV synthesis. Triggered by the Builder
	 * "View Chart" button.
	 */
	openAnalyticsForPortfolio() {
		this.analyticsMode = "portfolio";
	}

	/** Close the Analytics column, collapsing back to Estado B. */
	clearAnalytics() {
		this.analyticsMode = null;
		this.selectedAnalyticsFund = null;
	}

	/**
	 * Reset layout-scoped state when the PM (re-)enters /portfolio
	 * from another route. The 3rd column must always start closed
	 * per the design spec §1.3 "Reset ao voltar" rule. Called from
	 * `onMount` of `routes/(app)/portfolio/+page.svelte`.
	 *
	 * This is separate from `selectPortfolio()` because the PM may
	 * re-enter with the same portfolio still selected — we don't
	 * want to drop workspace state, only layout state.
	 */
	resetBuilderEntry() {
		this.analyticsMode = null;
		this.selectedAnalyticsFund = null;
	}

	selectPortfolio(p: ModelPortfolio) {
		// Increment generation to invalidate any in-flight async loads
		this._generation++;
		// Cancel any in-flight construction run stream belonging to the
		// previous portfolio — prevents stale SSE events from clobbering
		// the newly-selected portfolio.
		this._activeRunAbort?.abort();
		this._activeRunAbort = null;

		this.portfolio = p;
		this.localStress = null;
		this.localFactorAnalysis = null;
		this.localOverlap = null;
		this.rebalanceResult = null;
		this.attribution = null;
		this.driftAlerts = [];
		this.correlationRegime = null;
		this.riskBudget = null;
		this.advice = null;
		this.adviceFetched = false;
		this.lastError = null;
		this.navSeries = [];
		// Phase 4 — calibration + run reset on portfolio switch
		this.calibration = null;
		this.constructionRun = null;
		this.runPhase = "idle";
		this.runError = null;
		// Switching models is a hard reset of the analytics context —
		// the 3rd column closes and the PM starts fresh in Estado B.
		this.analyticsMode = null;
		this.selectedAnalyticsFund = null;
		// Fire-and-forget: load track-record, factor analysis, attribution, drift,
		// + Phase 4 calibration surface so the Builder right stack can render.
		this.loadTrackRecord();
		this.loadDriftAlerts();
		this.loadCalibration();

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
		const gen = this._generation;
		this.isLoadingTrackRecord = true;

		try {
			const api = this.api();
			const result = await api.get<TrackRecord>(
				`/model-portfolios/${this.portfolioId}/track-record`,
			);
			if (gen !== this._generation) return; // stale — portfolio changed
			this.navSeries = result.nav_series ?? [];
		} catch (err) {
			if (gen !== this._generation) return;
			this.lastError = {
				action: "track-record",
				message: err instanceof Error ? err.message : "Failed to load track record",
				timestamp: Date.now(),
			};
			this.navSeries = [];
		} finally {
			if (gen === this._generation) this.isLoadingTrackRecord = false;
		}
	}

	async loadFactorAnalysis(profile: string) {
		const gen = this._generation;
		this.isLoadingFactorAnalysis = true;
		try {
			const api = this.api();
			const result = await api.get<FactorAnalysisResponse>(
				`/analytics/factor-analysis/${profile}`
			);
			if (gen !== this._generation) return;
			this.localFactorAnalysis = result;
			this.lastError = null;
		} catch (err: any) {
			if (gen !== this._generation) return;
			console.error("loadFactorAnalysis error:", err);
			this.lastError = {
				action: "factor-analysis",
				message: err.message || "Unknown error resolving factor analysis",
				timestamp: Date.now()
			};
		} finally {
			if (gen === this._generation) this.isLoadingFactorAnalysis = false;
		}
	}

	// ── Overlap loading (real API) ──────────────────────────────────

	async loadOverlap() {
		if (!this._getToken || !this.portfolioId) return;
		const gen = this._generation;
		this.isLoadingOverlap = true;
		try {
			const api = this.api();
			const result = await api.get<OverlapResult>(
				`/model-portfolios/${this.portfolioId}/overlap`
			);
			if (gen !== this._generation) return;
			this.localOverlap = result;
		} catch (err: any) {
			if (gen !== this._generation) return;
			console.error("loadOverlap error:", err);
			this.lastError = {
				action: "overlap",
				message: err.message || "Unknown error fetching overlaps",
				timestamp: Date.now()
			};
			this.localOverlap = null;
		} finally {
			if (gen === this._generation) this.isLoadingOverlap = false;
		}
	}

	// ── Attribution loading (Brinson-Fachler) ───────────────────────

	async loadAttribution(profile: string) {
		if (!this._getToken) return;
		const gen = this._generation;
		this.isLoadingAttribution = true;
		try {
			const api = this.api();
			const result = await api.get<AttributionResult>(
				`/analytics/attribution/${profile}`,
			);
			if (gen !== this._generation) return;
			this.attribution = result;
		} catch {
			if (gen !== this._generation) return;
			this.attribution = null;
		} finally {
			if (gen === this._generation) this.isLoadingAttribution = false;
		}
	}

	// ── Drift alerts loading ────────────────────────────────────────

	async loadDriftAlerts() {
		if (!this._getToken) return;
		const gen = this._generation;
		this.isLoadingDrift = true;
		try {
			const api = this.api();
			const result = await api.get<StrategyDriftAlert[]>(
				"/analytics/strategy-drift/alerts",
				{ limit: "50" },
			);
			if (gen !== this._generation) return;
			this.driftAlerts = result;
		} catch {
			if (gen !== this._generation) return;
			this.driftAlerts = [];
		} finally {
			if (gen === this._generation) this.isLoadingDrift = false;
		}
	}

	// ── Correlation regime loading ──────────────────────────────────

	async loadCorrelationRegime(profile: string) {
		if (!this._getToken) return;
		const gen = this._generation;
		this.isLoadingCorrelationRegime = true;
		try {
			const api = this.api();
			const result = await api.get<CorrelationRegimeResult>(
				`/analytics/correlation-regime/${profile}`,
				{ window_days: "60" },
			);
			if (gen !== this._generation) return;
			this.correlationRegime = result;
		} catch {
			if (gen !== this._generation) return;
			this.correlationRegime = null;
		} finally {
			if (gen === this._generation) this.isLoadingCorrelationRegime = false;
		}
	}

	// ── Risk budget loading (on-demand) ─────────────────────────────

	async loadRiskBudget() {
		if (!this._getToken || !this.portfolio?.profile) return;
		const gen = this._generation;
		this.isLoadingRiskBudget = true;
		try {
			const api = this.api();
			const result = await api.post<RiskBudgetResult>(
				`/analytics/risk-budget/${this.portfolio.profile}`,
				{},
			);
			if (gen !== this._generation) return;
			this.riskBudget = result;
		} catch {
			if (gen !== this._generation) return;
			this.riskBudget = null;
		} finally {
			if (gen === this._generation) this.isLoadingRiskBudget = false;
		}
	}

	// ── Universe loading (real API) ──────────────────────────────────

	/** True while universe is being fetched from API. */
	isLoadingUniverse = $state(false);

	/** Load approved universe funds from GET /universe.
	 *
	 * Passes the current Builder `funds` as `current_holdings` query
	 * param so the backend can enrich each row with
	 * `correlation_to_portfolio` on-the-fly (spec §3.4). When the
	 * portfolio is empty, the param is omitted and every row's
	 * correlation comes back `null`.
	 */
	async loadUniverse() {
		if (!this._getToken) return;
		this.isLoadingUniverse = true;

		try {
			const api = this.api();
			// Send the list of currently allocated instrument IDs so
			// the backend can correlate each candidate against this
			// exact portfolio composition. The query param accepts
			// comma-separated UUIDs; empty means "no portfolio context,
			// return correlation_to_portfolio=null for everyone".
			const holdingIds = this.funds
				.map((f) => f.instrument_id)
				.filter((id): id is string => !!id);
			const qs = holdingIds.length > 0
				? `?current_holdings=${holdingIds.join(",")}`
				: "";
			const result = await api.get<UniverseApiItem[]>(`/universe${qs}`);

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
					aum_usd: r.aum_usd ?? null,
					expense_ratio: r.expense_ratio ?? null,
					return_3y_ann: r.return_3y_ann ?? null,
					sharpe_1y: r.sharpe_1y ?? null,
					max_drawdown_1y: r.max_drawdown_1y ?? null,
					blended_momentum_score: r.blended_momentum_score ?? null,
					liquidity_tier: r.liquidity_tier ?? null,
					correlation_to_portfolio: r.correlation_to_portfolio ?? null,
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

	/**
	 * Remove a fund from the allocation (reverse of addFundToBlock).
	 *
	 * The Portfolio Builder is a staging area — the portfolio is not
	 * "live" until explicitly activated. Removing a fund here simply
	 * takes it out of `fund_selection_schema.funds`, which makes the
	 * UniverseTable's `isAllocated` check return `false` and the fund
	 * appears re-enabled (full opacity, draggable) back in the
	 * Approved Universe column. This is the user's primary undo
	 * action while modelling.
	 *
	 * After removal, weights within the affected block are redistributed
	 * equally across the remaining funds, matching the convention of
	 * `addFundToBlock`. When the last fund in a block is removed, the
	 * block weight falls to 0 naturally.
	 *
	 * Returns `true` if the fund was found and removed, `false` if not.
	 */
	removeFund(instrumentId: string): boolean {
		if (!this.portfolio?.fund_selection_schema?.funds) return false;
		const schema = this.portfolio.fund_selection_schema;
		const idx = schema.funds.findIndex((f) => f.instrument_id === instrumentId);
		if (idx === -1) return false;

		const removed = schema.funds[idx]!;
		schema.funds.splice(idx, 1);

		// Re-equalise the weights in the block that just lost a fund.
		const remainingInBlock = schema.funds.filter((f) => f.block_id === removed.block_id);
		if (remainingInBlock.length > 0) {
			const equalWeight = Math.round((1 / remainingInBlock.length) * 10000) / 10000;
			for (const f of remainingInBlock) {
				f.weight = equalWeight;
			}
		}

		// Trigger reactivity
		this.portfolio = { ...this.portfolio };
		return true;
	}

	// ── Phase 4 — Calibration load / preview / apply ────────────────

	/** Load the 63-input calibration surface for the active portfolio. */
	async loadCalibration() {
		if (!this._getToken || !this.portfolioId) return;
		const gen = this._generation;
		this.isLoadingCalibration = true;
		try {
			const api = this.api();
			const result = await api.get<PortfolioCalibration>(
				`/model-portfolios/${this.portfolioId}/calibration`,
			);
			if (gen !== this._generation) return;
			this.calibration = result;
		} catch (err) {
			if (gen !== this._generation) return;
			this.lastError = {
				action: "calibration-load",
				message: err instanceof Error ? err.message : "Failed to load calibration",
				timestamp: Date.now(),
			};
			this.calibration = null;
		} finally {
			if (gen === this._generation) this.isLoadingCalibration = false;
		}
	}

	/**
	 * Persist a Builder CalibrationPanel Apply edit. Accepts the
	 * partial update body and replaces ``this.calibration`` with the
	 * post-update snapshot returned from the backend.
	 *
	 * DL5 — Apply is the ONLY persistence moment. Preview is never
	 * reactive; it is only fired when the user presses the Preview
	 * button in the panel (debounced client-side).
	 */
	async applyCalibration(patch: PortfolioCalibrationUpdate): Promise<PortfolioCalibration | null> {
		if (!this._getToken || !this.portfolioId) return null;
		this.isApplyingCalibration = true;
		this.lastError = null;
		try {
			const api = this.api();
			const result = await api.put<PortfolioCalibration>(
				`/model-portfolios/${this.portfolioId}/calibration`,
				patch,
			);
			this.calibration = result;
			return result;
		} catch (err) {
			this.lastError = {
				action: "calibration-apply",
				message: err instanceof Error ? err.message : "Failed to apply calibration",
				timestamp: Date.now(),
			};
			return null;
		} finally {
			this.isApplyingCalibration = false;
		}
	}

	// ── Phase 6 Block B — Portfolio Analytics surface data ───────────

	/**
	 * Phase 6 Block B — separate data slice for the /portfolio/analytics
	 * surface so it does not collide with the Builder's ``portfolio``
	 * field. The shell renders charts against this slice; switching the
	 * selected subject in the BottomTabDock triggers a fresh fetch via
	 * ``loadAnalyticsSubject``.
	 *
	 * The slice carries:
	 *   - portfolio: the selected ModelPortfolio detail (for state +
	 *     fund_selection_schema + profile)
	 *   - latestRun: the most recent persisted construction run with
	 *     stress_results, factor_exposure, ex_ante_metrics
	 *   - attribution / factor / correlationRegime / riskBudget:
	 *     profile-keyed analytics responses (only populated when the
	 *     portfolio is in "live" state — the existing routes require
	 *     a live portfolio for that profile)
	 *
	 * Strict empty states per OD-26 — every field starts as null and
	 * the chart components render an EmptyState when their slice is
	 * missing. No fabricated values, no MOCK data.
	 */
	analyticsPortfolio = $state.raw<ModelPortfolio | null>(null);
	analyticsLatestRun = $state.raw<ConstructionRunPayload | null>(null);
	analyticsAttribution = $state.raw<AttributionResult | null>(null);
	analyticsFactor = $state.raw<FactorAnalysisResponse | null>(null);
	analyticsCorrelationRegime = $state.raw<CorrelationRegimeResult | null>(null);
	analyticsRiskBudget = $state.raw<RiskBudgetResult | null>(null);
	/** NAV series for the analytics-selected portfolio (separate from
	 *  ``navSeries`` which tracks the Builder selection). */
	analyticsNavSeries = $state.raw<NAVPoint[]>([]);
	isLoadingAnalyticsSubject = $state(false);
	analyticsSubjectError = $state<string | null>(null);

	/** Generation counter to invalidate stale loadAnalyticsSubject responses. */
	private _analyticsGen = 0;

	/**
	 * Load every analytics slice for a model portfolio. Called by the
	 * /portfolio/analytics page when the user selects a subject in the
	 * BottomTabDock or via the FilterRail subject list.
	 *
	 * Fetches in parallel:
	 *   - GET /model-portfolios/{id}                      (detail)
	 *   - GET /model-portfolios/{id}/runs/latest          (Phase 6 Block B)
	 *   - GET /analytics/attribution/{profile}            (404 OK)
	 *   - GET /analytics/factor-analysis/{profile}        (404 OK)
	 *   - GET /analytics/correlation-regime/{profile}     (404 OK)
	 *
	 * Risk budget is on-demand only — the route is POST-based and
	 * triggers heavy computation. The PM can request it from the
	 * RiskAttributionBarChart card via a "Compute" CTA.
	 *
	 * 404 / 422 from the analytics routes are CAUGHT and surfaced as
	 * null slices — the chart components render strict empty states
	 * (OD-26). Only a 5xx on the portfolio detail call propagates as
	 * an error message via ``analyticsSubjectError``.
	 */
	async loadAnalyticsSubject(portfolioId: string): Promise<void> {
		if (!this._getToken) return;
		const gen = ++this._analyticsGen;
		this.isLoadingAnalyticsSubject = true;
		this.analyticsSubjectError = null;

		// Reset slices upfront so the shell shows loading skeletons
		// instead of stale data from the previous subject.
		this.analyticsPortfolio = null;
		this.analyticsLatestRun = null;
		this.analyticsAttribution = null;
		this.analyticsFactor = null;
		this.analyticsCorrelationRegime = null;
		this.analyticsRiskBudget = null;
		this.analyticsNavSeries = [];

		try {
			const api = this.api();
			const portfolio = await api.get<ModelPortfolio>(
				`/model-portfolios/${portfolioId}`,
			);
			if (gen !== this._analyticsGen) return;
			this.analyticsPortfolio = portfolio;

			// Latest run + NAV series are best-effort. NAV series feeds
			// the Discovery NavHero / Drawdown chart adapters.
			const [latestRun, trackRecord] = await Promise.all([
				api
					.get<ConstructionRunPayload | null>(
						`/model-portfolios/${portfolioId}/runs/latest`,
					)
					.catch(() => null),
				api
					.get<TrackRecord>(`/model-portfolios/${portfolioId}/track-record`)
					.catch(() => null),
			]);
			if (gen !== this._analyticsGen) return;
			this.analyticsLatestRun = latestRun;
			this.analyticsNavSeries = trackRecord?.nav_series ?? [];

			// Profile-keyed analytics — only meaningful when the
			// portfolio is in "live" state because the routes require
			// a live model_portfolio for that profile.
			const profile = portfolio.profile;
			if (portfolio.state === "live" && profile) {
				const [attribution, factor, correlationRegime] = await Promise.all([
					api
						.get<AttributionResult>(`/analytics/attribution/${profile}`)
						.catch(() => null),
					api
						.get<FactorAnalysisResponse>(`/analytics/factor-analysis/${profile}`)
						.catch(() => null),
					api
						.get<CorrelationRegimeResult>(
							`/analytics/correlation-regime/${profile}?window_days=60`,
						)
						.catch(() => null),
				]);
				if (gen !== this._analyticsGen) return;
				this.analyticsAttribution = attribution;
				this.analyticsFactor = factor;
				this.analyticsCorrelationRegime = correlationRegime;
			}
		} catch (err) {
			if (gen !== this._analyticsGen) return;
			this.analyticsSubjectError = err instanceof Error
				? err.message
				: "Failed to load analytics subject";
		} finally {
			if (gen === this._analyticsGen) {
				this.isLoadingAnalyticsSubject = false;
			}
		}
	}

	/** Clear the analytics slice — called on route unmount. */
	resetAnalyticsSubject() {
		this._analyticsGen++;
		this.analyticsPortfolio = null;
		this.analyticsLatestRun = null;
		this.analyticsAttribution = null;
		this.analyticsFactor = null;
		this.analyticsCorrelationRegime = null;
		this.analyticsRiskBudget = null;
		this.analyticsNavSeries = [];
		this.analyticsSubjectError = null;
		this.isLoadingAnalyticsSubject = false;
	}

	// ── Phase 5 Task 5.2 — State machine transitions ─────────────────

	/**
	 * POST /model-portfolios/{id}/transitions — apply a state-machine
	 * action and refresh ``this.portfolio`` with the freshly-serialized
	 * response (carrying new ``state``, ``state_changed_at``, and
	 * ``allowed_actions``).
	 *
	 * The Builder action bar (Phase 5 Task 5.2) calls this directly.
	 * Returns the updated portfolio so the caller can branch on
	 * success/failure without re-reading the store.
	 *
	 * Per DL3 — never inspect ``state`` to decide whether to render
	 * a button. The backend's ``allowed_actions`` is the only source
	 * of truth for action visibility.
	 */
	async applyTransition(
		action: string,
		opts: { reason?: string; metadata?: Record<string, unknown> } = {},
	): Promise<ModelPortfolio | null> {
		if (!this._getToken || !this.portfolioId) return null;
		this.lastError = null;
		try {
			const api = this.api();
			const body: Record<string, unknown> = { action };
			if (opts.reason && opts.reason.trim().length > 0) {
				body.reason = opts.reason.trim();
			}
			if (opts.metadata && Object.keys(opts.metadata).length > 0) {
				body.metadata = opts.metadata;
			}
			const updated = await api.post<ModelPortfolio>(
				`/model-portfolios/${this.portfolioId}/transitions`,
				body,
			);
			// Refresh the workspace's portfolio view so action buttons
			// re-render against the new ``allowed_actions`` immediately.
			this.portfolio = updated;
			return updated;
		} catch (err) {
			this.lastError = {
				action: `transition:${action}`,
				message: err instanceof Error ? err.message : "Failed to apply transition",
				timestamp: Date.now(),
			};
			return null;
		}
	}

	// ── Phase 5 Task 5.1 — Create new portfolio (NewPortfolioDialog) ──

	/**
	 * POST /model-portfolios — create a new draft portfolio.
	 *
	 * The backend (Phase 5 Task 5.1 backend extension) hydrates the
	 * response with ``allowed_actions`` from the state machine and
	 * seeds the paired ``portfolio_calibration`` row with migration
	 * 0100 defaults so the Builder can immediately render the
	 * canonical ``[construct, archive]`` action set on success.
	 *
	 * Caller is responsible for navigating to the new portfolio —
	 * this method only persists and returns the new row.
	 */
	async createPortfolio(payload: Record<string, unknown>): Promise<ModelPortfolio | null> {
		if (!this._getToken) return null;
		this.lastError = null;
		try {
			const api = this.api();
			const created = await api.post<ModelPortfolio>(
				"/model-portfolios",
				payload,
			);
			return created;
		} catch (err) {
			this.lastError = {
				action: "create-portfolio",
				message: err instanceof Error ? err.message : "Failed to create portfolio",
				timestamp: Date.now(),
			};
			return null;
		}
	}

	// ── Phase 4 — Construction run loader ───────────────────────────

	/** Fetch a persisted construction run by id into ``constructionRun``. */
	async loadConstructionRun(runId: string) {
		if (!this._getToken || !this.portfolioId) return;
		const gen = this._generation;
		this.isLoadingRun = true;
		try {
			const api = this.api();
			const result = await api.get<ConstructionRunPayload>(
				`/model-portfolios/${this.portfolioId}/runs/${runId}`,
			);
			if (gen !== this._generation) return;
			this.constructionRun = result;
		} catch (err) {
			if (gen !== this._generation) return;
			this.lastError = {
				action: "run-load",
				message: err instanceof Error ? err.message : "Failed to load construction run",
				timestamp: Date.now(),
			};
			this.constructionRun = null;
		} finally {
			if (gen === this._generation) this.isLoadingRun = false;
		}
	}

	// ── Construction Advisor (generation-guarded) ───────────────────────────

	async fetchConstructionAdvice() {
		if (!this._getToken || !this.portfolioId) return;
		const gen = this._generation;
		this.isLoadingAdvice = true;
		this.advice = null;

		try {
			const api = this.api();
			const result = await api.post<ConstructionAdvice>(
				`/model-portfolios/${this.portfolioId}/construction-advice`,
				{},
			);
			if (gen !== this._generation) return; // stale — portfolio changed
			this.advice = result;
		} catch (err) {
			if (gen !== this._generation) return;
			this.lastError = {
				action: "construction-advice",
				message: err instanceof Error ? err.message : "Failed to load construction advice",
				timestamp: Date.now(),
			};
		} finally {
			if (gen === this._generation) {
				this.isLoadingAdvice = false;
				this.adviceFetched = true;
			}
		}
	}

	// ── Portfolio Activation ────────────────────────────────────────────────

	async activatePortfolio() {
		if (!this._getToken || !this.portfolioId) return;
		this.isActivating = true;
		this.lastError = null;

		try {
			const api = this.api();
			const result = await api.post<ModelPortfolio>(
				`/model-portfolios/${this.portfolioId}/activate`,
				{},
			);
			this.portfolio = result;
			this.advice = null; // advisor no longer relevant after activation
		} catch (err) {
			this.lastError = {
				action: "activate",
				message: err instanceof Error ? err.message : "Portfolio activation failed",
				timestamp: Date.now(),
			};
			throw err; // re-throw so ConsequenceDialog can handle
		} finally {
			this.isActivating = false;
		}
	}

	// ── Construction & Live Rebalance ─────────────────────────────────────────

	/**
	 * Kick off a Phase 3 Job-or-Stream construction run (DL18 P2).
	 *
	 * Flow:
	 *   1. POST /model-portfolios/{id}/construct → 202 ConstructRunAccepted
	 *   2. Open fetch()+ReadableStream SSE at stream_url (NEVER EventSource
	 *      — Clerk JWT needs Authorization header, DL15).
	 *   3. Advance runPhase on each event ('run_started' | 'optimizer_started'
	 *      | 'stress_started').
	 *   4. On terminal 'done', fetch the run detail via loadConstructionRun
	 *      and transition runPhase → 'done'. Callers that care about the
	 *      resolution await the returned promise; it settles on terminal.
	 *   5. On terminal 'error', set runError + runPhase → 'error'.
	 *
	 * The legacy ``isConstructing`` boolean is kept in sync for
	 * backwards-compatibility with components that still read it.
	 */
	async runConstructJob(): Promise<ConstructionRunPayload | null> {
		if (!this._getToken || !this.portfolioId) return null;

		// Cancel any in-flight stream if the user re-presses Run Construct.
		this._activeRunAbort?.abort();
		const abort = new AbortController();
		this._activeRunAbort = abort;

		this.runPhase = "running";
		this.runError = null;
		this.isConstructing = true;
		this.lastError = null;

		try {
			// ── 1. POST /construct → 202 ──
			const api = this.api();
			const accepted = await api.post<ConstructRunAccepted>(
				`/model-portfolios/${this.portfolioId}/construct`,
				undefined,
				{ timeoutMs: 130_000 }, // backend bound is 120s + 10s margin
			);

			// If the worker completed synchronously (cached or very fast),
			// skip the SSE dance and load the run immediately.
			if (accepted.status === "succeeded" || accepted.status === "cached") {
				await this.loadConstructionRun(accepted.run_id);
				this.runPhase = "done";
				return this.constructionRun;
			}
			if (accepted.status === "failed") {
				this.runPhase = "error";
				this.runError = "Construction failed before streaming started";
				return null;
			}

			// ── 2. Stream SSE until terminal ──
			// The backend emits stream_url as ``/api/v1/jobs/{id}/stream``.
			// VITE_API_BASE_URL already contains the ``/api/v1`` suffix
			// (e.g. http://localhost:8000/api/v1), so we strip that before
			// concatenating the absolute stream path.
			const token = await this._getToken();
			const envBase =
				(import.meta.env.VITE_API_BASE_URL as string | undefined) ??
				"http://localhost:8000/api/v1";
			const host = envBase.replace(/\/api\/v1\/?$/, "");
			const streamUrl = accepted.stream_url.startsWith("http")
				? accepted.stream_url
				: `${host}${accepted.stream_url}`;

			const res = await fetch(streamUrl, {
				headers: {
					Authorization: `Bearer ${token}`,
					Accept: "text/event-stream",
				},
				signal: abort.signal,
			});

			if (!res.ok || !res.body) {
				throw new Error(`SSE stream failed: HTTP ${res.status}`);
			}

			const reader = res.body.getReader();
			const decoder = new TextDecoder();
			let buffer = "";
			let currentData = "";
			let terminal: ConstructRunEvent | null = null;

			streamLoop: while (true) {
				const { done, value } = await reader.read();
				if (done) break;
				buffer += decoder.decode(value, { stream: true });
				buffer = buffer.replace(/\r\n/g, "\n");
				const lines = buffer.split("\n");
				buffer = lines.pop() ?? "";

				for (const line of lines) {
					if (line.startsWith("data:")) {
						currentData += (currentData ? "\n" : "") + line.slice(5).replace(/^ /, "");
					} else if (line === "") {
						if (currentData) {
							let parsed: ConstructRunEvent | null = null;
							try {
								parsed = JSON.parse(currentData) as ConstructRunEvent;
							} catch {
								parsed = null;
							}
							if (parsed) {
								this._applyRunEvent(parsed);
								if (parsed.event === "done" || parsed.event === "error") {
									terminal = parsed;
									break streamLoop;
								}
							}
							currentData = "";
						}
					}
				}
			}

			reader.cancel().catch(() => {
				/* ignore abort noise */
			});

			if (!terminal) {
				this.runPhase = "error";
				this.runError = "Stream closed before terminal event";
				return null;
			}

			if (terminal.event === "error") {
				this.runPhase = "error";
				this.runError = terminal.reason ?? "Construction failed";
				return null;
			}

			// ── 3. Fetch the persisted run ──
			const runId = terminal.run_id ?? accepted.run_id;
			await this.loadConstructionRun(runId);
			this.runPhase = "done";
			return this.constructionRun;
		} catch (err) {
			if ((err as { name?: string } | null)?.name === "AbortError") {
				return null;
			}
			this.runPhase = "error";
			this.runError = err instanceof Error ? err.message : "Construction failed";
			this.lastError = {
				action: "construct",
				message: this.runError,
				timestamp: Date.now(),
			};
			return null;
		} finally {
			this.isConstructing = false;
			if (this._activeRunAbort === abort) this._activeRunAbort = null;
		}
	}

	/** Legacy alias — kept so existing components can still call ``constructPortfolio``. */
	async constructPortfolio() {
		await this.runConstructJob();
	}

	/** Apply a single SSE event to ``runPhase``. */
	private _applyRunEvent(ev: ConstructRunEvent) {
		switch (ev.event) {
			case "run_started":
				this.runPhase = "running";
				break;
			case "optimizer_started":
				this.runPhase = "optimizer";
				break;
			case "stress_started":
				this.runPhase = "stress";
				break;
			case "done":
				this.runPhase = "done";
				break;
			case "error":
				this.runPhase = "error";
				this.runError = ev.reason ?? "Construction failed";
				break;
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
