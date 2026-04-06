/**
 * Portfolio Workspace Store — drift analysis, rebalance preview, strategy alerts.
 *
 * Lives in the portfolio detail context (portfolio/models/[portfolioId]).
 * Manages three async data channels:
 *   1. Live Drift: GET /model-portfolios/{id}/drift/live (debounced polling)
 *   2. Rebalance Preview: POST /model-portfolios/{id}/rebalance/preview (on-demand)
 *   3. Strategy Drift Alerts: GET /analytics/strategy-drift/alerts (on-demand)
 *
 * CRITICAL: Drift polling uses a debounce (default 30s) to protect the backend.
 * The store exposes a `refreshDrift()` for manual refresh on material events.
 *
 * No localStorage. All state is in-memory. Svelte 5 runes.
 */

import { createClientApiClient } from "$lib/api/client";

// ── Types ───────────────────────────────────────────────────

export interface BlockDrift {
	block_id: string;
	current_weight: number;
	target_weight: number;
	absolute_drift: number;
	relative_drift: number;
	status: "ok" | "maintenance" | "urgent";
}

export interface LiveDriftResult {
	portfolio_id: string;
	profile: string;
	as_of: string;
	total_aum: number;
	blocks: BlockDrift[];
	max_drift_pct: number;
	overall_status: "ok" | "maintenance" | "urgent";
	rebalance_recommended: boolean;
	estimated_turnover: number;
	latest_nav_date: string | null;
}

export interface SuggestedTrade {
	instrument_id: string;
	fund_name: string;
	block_id: string;
	action: "BUY" | "SELL" | "HOLD";
	current_weight: number;
	target_weight: number;
	delta_weight: number;
	current_value: number;
	target_value: number;
	trade_value: number;
	estimated_quantity: number;
}

export interface WeightDelta {
	block_id: string;
	current_weight: number;
	target_weight: number;
	delta_pp: number;
}

export interface RebalancePreviewResult {
	portfolio_id: string;
	portfolio_name: string;
	profile: string;
	total_aum: number;
	cash_available: number;
	total_trades: number;
	estimated_turnover_pct: number;
	trades: SuggestedTrade[];
	weight_comparison: WeightDelta[];
	cvar_95_projected: number | null;
	cvar_limit: number | null;
	cvar_warning: boolean;
}

export interface StrategyDriftAlert {
	instrument_id: string;
	instrument_name: string;
	severity: "none" | "moderate" | "severe";
	anomalous_count: number;
	total_metrics: number;
	metric_details: Record<string, { z_score: number; is_anomalous: boolean }>;
	computed_at: string;
}

export interface MonitoringAlert {
	alert_type: string;
	severity: string;
	title: string;
	detail: string;
	entity_id: string | null;
	entity_type: string | null;
}

// ── Store Interface ─────────────────────────────────────────

export interface PortfolioWorkspaceStore {
	// Drift
	readonly drift: LiveDriftResult | null;
	readonly driftLoading: boolean;
	readonly driftError: string | null;
	refreshDrift: () => void;
	// Rebalance Preview
	readonly rebalancePreview: RebalancePreviewResult | null;
	readonly rebalanceLoading: boolean;
	readonly rebalanceError: string | null;
	requestRebalancePreview: (holdings: { instrument_id: string; quantity: number; current_price: number }[], cashAvailable?: number) => void;
	// Strategy Drift Alerts
	readonly strategyAlerts: StrategyDriftAlert[];
	readonly strategyAlertsLoading: boolean;
	readonly strategyAlertsError: string | null;
	refreshStrategyAlerts: () => void;
	// Monitoring Alerts
	readonly monitoringAlerts: MonitoringAlert[];
	readonly monitoringAlertsLoading: boolean;
	refreshMonitoringAlerts: () => void;
	// Lifecycle
	startPolling: () => void;
	destroy: () => void;
}

// ── Config ──────────────────────────────────────────────────

export interface WorkspaceConfig {
	portfolioId: string;
	getToken: () => Promise<string>;
	/** Drift poll interval in ms (default: 30_000) */
	driftPollMs?: number;
}

// ── Constants ───────────────────────────────────────────────

const DEFAULT_DRIFT_POLL_MS = 30_000;

// ── Store Factory ───────────────────────────────────────────

export function createPortfolioWorkspace(config: WorkspaceConfig): PortfolioWorkspaceStore {
	const { portfolioId, getToken, driftPollMs = DEFAULT_DRIFT_POLL_MS } = config;
	const api = createClientApiClient(getToken);

	// ── Drift State ─────────────────────────────────────────
	let drift = $state<LiveDriftResult | null>(null);
	let driftLoading = $state(false);
	let driftError = $state<string | null>(null);
	let driftTimer: ReturnType<typeof setInterval> | null = null;

	async function fetchDrift(): Promise<void> {
		if (driftLoading) return; // Prevent concurrent calls
		driftLoading = true;
		driftError = null;
		try {
			drift = await api.get<LiveDriftResult>(
				`/model-portfolios/${portfolioId}/drift/live`,
			);
		} catch (e) {
			driftError = e instanceof Error ? e.message : "Failed to fetch drift";
		} finally {
			driftLoading = false;
		}
	}

	function refreshDrift(): void {
		fetchDrift();
	}

	// ── Rebalance Preview State ─────────────────────────────
	let rebalancePreview = $state<RebalancePreviewResult | null>(null);
	let rebalanceLoading = $state(false);
	let rebalanceError = $state<string | null>(null);

	async function requestRebalancePreview(
		holdings: { instrument_id: string; quantity: number; current_price: number }[],
		cashAvailable: number = 0,
	): Promise<void> {
		if (rebalanceLoading) return;
		rebalanceLoading = true;
		rebalanceError = null;
		try {
			rebalancePreview = await api.post<RebalancePreviewResult>(
				`/model-portfolios/${portfolioId}/rebalance/preview`,
				{
					current_holdings: holdings,
					cash_available: cashAvailable,
				},
			);
		} catch (e) {
			rebalanceError = e instanceof Error ? e.message : "Failed to fetch rebalance preview";
		} finally {
			rebalanceLoading = false;
		}
	}

	// ── Strategy Drift Alerts State ─────────────────────────
	let strategyAlerts = $state<StrategyDriftAlert[]>([]);
	let strategyAlertsLoading = $state(false);
	let strategyAlertsError = $state<string | null>(null);

	async function fetchStrategyAlerts(): Promise<void> {
		if (strategyAlertsLoading) return;
		strategyAlertsLoading = true;
		strategyAlertsError = null;
		try {
			const resp = await api.get<{ alerts: StrategyDriftAlert[] }>(
				"/analytics/strategy-drift/alerts",
				{ severity: "moderate" },
			);
			strategyAlerts = resp.alerts ?? [];
		} catch (e) {
			strategyAlertsError = e instanceof Error ? e.message : "Failed to fetch strategy alerts";
		} finally {
			strategyAlertsLoading = false;
		}
	}

	// ── Monitoring Alerts State ─────────────────────────────
	let monitoringAlerts = $state<MonitoringAlert[]>([]);
	let monitoringAlertsLoading = $state(false);

	async function fetchMonitoringAlerts(): Promise<void> {
		if (monitoringAlertsLoading) return;
		monitoringAlertsLoading = true;
		try {
			const resp = await api.get<{ alerts: MonitoringAlert[] }>(
				"/monitoring/alerts",
			);
			monitoringAlerts = resp.alerts ?? [];
		} catch {
			// Non-critical — silently ignore
		} finally {
			monitoringAlertsLoading = false;
		}
	}

	// ── Polling Lifecycle ───────────────────────────────────

	function startPolling(): void {
		// Initial fetch
		fetchDrift();
		fetchStrategyAlerts();
		fetchMonitoringAlerts();

		// Drift polling on interval (debounced by nature — fixed interval)
		driftTimer = setInterval(fetchDrift, driftPollMs);
	}

	function destroy(): void {
		if (driftTimer) {
			clearInterval(driftTimer);
			driftTimer = null;
		}
	}

	// ── Public API ──────────────────────────────────────────

	return {
		get drift() { return drift; },
		get driftLoading() { return driftLoading; },
		get driftError() { return driftError; },
		refreshDrift,
		get rebalancePreview() { return rebalancePreview; },
		get rebalanceLoading() { return rebalanceLoading; },
		get rebalanceError() { return rebalanceError; },
		requestRebalancePreview,
		get strategyAlerts() { return strategyAlerts; },
		get strategyAlertsLoading() { return strategyAlertsLoading; },
		get strategyAlertsError() { return strategyAlertsError; },
		refreshStrategyAlerts: fetchStrategyAlerts,
		get monitoringAlerts() { return monitoringAlerts; },
		get monitoringAlertsLoading() { return monitoringAlertsLoading; },
		refreshMonitoringAlerts: fetchMonitoringAlerts,
		startPolling,
		destroy,
	};
}
