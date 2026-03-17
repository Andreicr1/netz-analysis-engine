/**
 * Risk Store — in-memory, SSE primary, polling fallback.
 *
 * Declared once in (team)/+layout.svelte, shared via Svelte context.
 * No localStorage. Status-aware with stale detection.
 *
 * Combines CVaR, drift alerts, and regime from a single SSE connection.
 */

import { isStale } from "./stale.js";

export type StoreStatus = "loading" | "ready" | "error" | "stale";

export interface CVaRStatus {
	profile: string;
	calc_date: string | null;
	cvar_current: number | null;
	cvar_limit: number | null;
	cvar_utilized_pct: number | null;
	trigger_status: string | null;
	regime: string | null;
	consecutive_breach_days: number;
}

export interface CVaRPoint {
	date: string;
	cvar: number;
}

export interface DriftAlert {
	instrument_name: string;
	instrument_id?: string;
	dtw_score: number;
}

export interface BehaviorAlert {
	instrument_name: string;
	instrument_id?: string;
	severity: string;
	anomalous_count: number;
	total_metrics: number;
}

export interface RegimeData {
	regime: string;
	confidence: number | null;
	timestamp: string | null;
}

export interface RiskStoreState {
	status: StoreStatus;
	lastUpdated: Date | null;
	error: string | null;
	cvarByProfile: Record<string, CVaRStatus>;
	cvarHistoryByProfile: Record<string, CVaRPoint[]>;
	regime: RegimeData | null;
	regimeHistory: Array<{ date: string; regime: string }>;
	driftAlerts: {
		dtw_alerts: DriftAlert[];
		behavior_change_alerts: BehaviorAlert[];
	};
	macroIndicators: Record<string, unknown> | null;
}

export interface RiskStoreConfig {
	profileIds: string[];
	getToken: () => Promise<string>;
	apiBaseUrl: string;
	sseEndpoint?: string;
	pollingFallbackMs?: number;
}

/**
 * Create a risk store. Call once in root layout, share via context.
 */
export function createRiskStore(config: RiskStoreConfig) {
	const { profileIds, getToken, apiBaseUrl, pollingFallbackMs = 30_000 } = config;

	// Reactive state
	let status = $state<StoreStatus>("loading");
	let lastUpdated = $state<Date | null>(null);
	let error = $state<string | null>(null);
	let cvarByProfile = $state<Record<string, CVaRStatus>>({});
	let cvarHistoryByProfile = $state<Record<string, CVaRPoint[]>>({});
	let regime = $state<RegimeData | null>(null);
	let regimeHistory = $state<Array<{ date: string; regime: string }>>([]);
	let driftAlerts = $state<{ dtw_alerts: DriftAlert[]; behavior_change_alerts: BehaviorAlert[] }>({
		dtw_alerts: [],
		behavior_change_alerts: [],
	});
	let macroIndicators = $state<Record<string, unknown> | null>(null);

	let pollTimer: ReturnType<typeof setTimeout> | undefined;

	// Check staleness periodically
	function checkStale() {
		if (status === "ready" && isStale(lastUpdated)) {
			status = "stale";
		}
	}

	async function fetchAll() {
		try {
			const token = await getToken();
			const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

			// Parallel fetch all risk data
			const requests = [
				...profileIds.map((p) =>
					fetch(`${apiBaseUrl}/risk/cvar/${p}/status`, { headers }).then((r) => r.ok ? r.json() : null),
				),
				...profileIds.map((p) =>
					fetch(`${apiBaseUrl}/risk/cvar/${p}/history`, { headers }).then((r) => r.ok ? r.json() : null),
				),
				fetch(`${apiBaseUrl}/risk/regime`, { headers }).then((r) => r.ok ? r.json() : null),
				fetch(`${apiBaseUrl}/risk/regime/history`, { headers }).then((r) => r.ok ? r.json() : null),
				fetch(`${apiBaseUrl}/analytics/strategy-drift/alerts`, { headers }).then((r) => r.ok ? r.json() : null),
				fetch(`${apiBaseUrl}/macro/snapshot`, { headers }).then((r) => r.ok ? r.json() : null),
			];

			const results = await Promise.allSettled(requests);
			const n = profileIds.length;

			// Parse CVaR status per profile
			const newCvar: Record<string, CVaRStatus> = {};
			const newHistory: Record<string, CVaRPoint[]> = {};

			for (let i = 0; i < n; i++) {
				const p = profileIds[i]!;
				const statusResult = results[i];
				const historyResult = results[n + i];
				if (statusResult?.status === "fulfilled" && statusResult.value) {
					newCvar[p] = statusResult.value;
				}
				if (historyResult?.status === "fulfilled" && historyResult.value) {
					newHistory[p] = Array.isArray(historyResult.value) ? historyResult.value : historyResult.value.points ?? [];
				}
			}

			cvarByProfile = newCvar;
			cvarHistoryByProfile = newHistory;

			const regimeIdx = 2 * n;
			const regimeResult = results[regimeIdx];
			if (regimeResult?.status === "fulfilled" && regimeResult.value) {
				regime = regimeResult.value;
			}

			const regimeHistResult = results[regimeIdx + 1];
			if (regimeHistResult?.status === "fulfilled" && regimeHistResult.value) {
				regimeHistory = Array.isArray(regimeHistResult.value) ? regimeHistResult.value : regimeHistResult.value.history ?? [];
			}

			const driftResult = results[regimeIdx + 2];
			if (driftResult?.status === "fulfilled" && driftResult.value) {
				driftAlerts = driftResult.value;
			}

			const macroResult = results[regimeIdx + 3];
			if (macroResult?.status === "fulfilled" && macroResult.value) {
				macroIndicators = macroResult.value;
			}

			lastUpdated = new Date();
			status = "ready";
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to load risk data";
			status = "error";
		}
	}

	function startPolling() {
		stopPolling();
		pollTimer = setInterval(() => {
			fetchAll();
			checkStale();
		}, pollingFallbackMs);
	}

	function stopPolling() {
		if (pollTimer) {
			clearInterval(pollTimer);
			pollTimer = undefined;
		}
	}

	async function refresh() {
		status = "loading";
		await fetchAll();
	}

	return {
		get status() { return status; },
		get lastUpdated() { return lastUpdated; },
		get error() { return error; },
		get cvarByProfile() { return cvarByProfile; },
		get cvarHistoryByProfile() { return cvarHistoryByProfile; },
		get regime() { return regime; },
		get regimeHistory() { return regimeHistory; },
		get driftAlerts() { return driftAlerts; },
		get macroIndicators() { return macroIndicators; },
		fetchAll,
		refresh,
		startPolling,
		stopPolling,
	};
}

export type RiskStore = ReturnType<typeof createRiskStore>;
