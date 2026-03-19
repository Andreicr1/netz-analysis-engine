/**
 * Risk Store — SSE-primary, poll-fallback. Single applyUpdate() gate.
 *
 * Declared once in (team)/+layout.svelte, shared via Svelte context.
 * No localStorage. Monotonic version counter prevents stale-poll-overwrite-fresh-SSE.
 * Freshness derived exclusively from server computed_at — Date.now() is forbidden.
 */

import { createClientApiClient } from "$lib/api/client";
import { createSSEStream, type SSEStatus } from "@netz/ui";
import { isStale } from "./stale.js";

// ── Types ───────────────────────────────────────────────────

export type ConnectionQuality = "live" | "degraded" | "offline";

export interface CVaRStatus {
	profile: string;
	calc_date: string | null;
	cvar_current: number | null;
	cvar_limit: number | null;
	cvar_utilized_pct: number | null;
	trigger_status: string | null;
	regime: string | null;
	consecutive_breach_days: number;
	computed_at?: string | null;
	next_expected_update?: string | null;
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

export type StoreStatus = "loading" | "ready" | "error" | "stale";

export interface RiskStoreState {
	status: StoreStatus;
	computedAt: string | null;
	nextExpectedUpdate: string | null;
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
	/** @deprecated Ignored — NetzApiClient resolves base URL internally. */
	apiBaseUrl?: string;
	sseEndpoint?: string;
	pollingFallbackMs?: number;
	heartbeatTimeoutMs?: number;
}

// ── Store Factory ───────────────────────────────────────────

/**
 * Create a risk store. Call once in root layout, share via context.
 *
 * SSE is the primary transport. Polling activates ONLY when SSE fails or
 * heartbeat times out. Every update passes through applyUpdate() which
 * enforces a monotonic version counter — stale poll data can never
 * overwrite fresh SSE data.
 */
export function createRiskStore(config: RiskStoreConfig) {
	const {
		profileIds,
		getToken,
		pollingFallbackMs = 30_000,
		heartbeatTimeoutMs = 45_000,
	} = config;

	// ── Monotonic version gate ──────────────────────────────
	let version = 0;

	// ── Reactive state ──────────────────────────────────────
	let status = $state<StoreStatus>("loading");
	let computedAt = $state<string | null>(null);
	let nextExpectedUpdate = $state<string | null>(null);
	let error = $state<string | null>(null);
	let cvarByProfile = $state<Record<string, CVaRStatus>>({});
	// Large arrays use $state.raw to avoid proxy overhead
	let cvarHistoryByProfile = $state.raw<Record<string, CVaRPoint[]>>({});
	let regime = $state<RegimeData | null>(null);
	let regimeHistory = $state.raw<Array<{ date: string; regime: string }>>([]);
	let driftAlerts = $state.raw<{ dtw_alerts: DriftAlert[]; behavior_change_alerts: BehaviorAlert[] }>({
		dtw_alerts: [],
		behavior_change_alerts: [],
	});
	let macroIndicators = $state<Record<string, unknown> | null>(null);

	// ── SSE state ───────────────────────────────────────────
	let sseStatus = $state<SSEStatus>("disconnected");
	let pollActive = $state(false);

	let pollTimer: ReturnType<typeof setTimeout> | undefined;
	let heartbeatTimer: ReturnType<typeof setTimeout> | undefined;
	let fetching = false;
	let sseConnection: ReturnType<typeof createSSEStream> | null = null;

	// ── Derived connection quality ──────────────────────────
	// Exposed as getter — consumers see $derived-like behavior
	function getConnectionQuality(): ConnectionQuality {
		if (sseStatus === "connected") return "live";
		if ((sseStatus === "connecting" || sseStatus === "error") && pollActive) return "degraded";
		return "offline";
	}

	// ── Single applyUpdate() gate ───────────────────────────
	// Every data source (SSE event, poll response) passes through here.
	// Monotonic version counter prevents stale-poll overwriting fresh SSE.

	interface RiskUpdate {
		version: number;
		cvarByProfile?: Record<string, CVaRStatus>;
		cvarHistoryByProfile?: Record<string, CVaRPoint[]>;
		regime?: RegimeData | null;
		regimeHistory?: Array<{ date: string; regime: string }>;
		driftAlerts?: { dtw_alerts: DriftAlert[]; behavior_change_alerts: BehaviorAlert[] };
		macroIndicators?: Record<string, unknown> | null;
	}

	function applyUpdate(update: RiskUpdate): boolean {
		// Reject stale updates — monotonic version enforcement
		if (update.version <= version) {
			return false;
		}
		version = update.version;

		if (update.cvarByProfile !== undefined) {
			cvarByProfile = update.cvarByProfile;
			// Extract computed_at from the first profile that has it
			const firstWithTimestamp = Object.values(update.cvarByProfile).find((c) => c.computed_at);
			if (firstWithTimestamp) {
				computedAt = firstWithTimestamp.computed_at ?? null;
				nextExpectedUpdate = firstWithTimestamp.next_expected_update ?? null;
			}
		}
		if (update.cvarHistoryByProfile !== undefined) {
			cvarHistoryByProfile = update.cvarHistoryByProfile;
		}
		if (update.regime !== undefined) {
			regime = update.regime;
		}
		if (update.regimeHistory !== undefined) {
			regimeHistory = update.regimeHistory;
		}
		if (update.driftAlerts !== undefined) {
			driftAlerts = update.driftAlerts;
		}
		if (update.macroIndicators !== undefined) {
			macroIndicators = update.macroIndicators;
		}

		// Staleness check uses server computed_at exclusively
		if (computedAt && isStale(computedAt)) {
			status = "stale";
		} else {
			status = "ready";
		}
		error = null;
		return true;
	}

	// ── SSE primary transport ───────────────────────────────

	function startSSE() {
		const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
		const sseUrl = config.sseEndpoint ?? `${apiBase}/risk/stream`;

		sseConnection = createSSEStream<Record<string, unknown>>({
			url: sseUrl,
			getToken,
			onEvent: (event) => {
				resetHeartbeat();
				// Each SSE event is a partial or full risk update
				const nextVersion = version + 1;
				const update: RiskUpdate = { version: nextVersion };

				if (event.cvar_by_profile) {
					update.cvarByProfile = event.cvar_by_profile as Record<string, CVaRStatus>;
				}
				if (event.regime) {
					update.regime = event.regime as RegimeData;
				}
				if (event.drift_alerts) {
					update.driftAlerts = event.drift_alerts as { dtw_alerts: DriftAlert[]; behavior_change_alerts: BehaviorAlert[] };
				}
				if (event.macro_indicators) {
					update.macroIndicators = event.macro_indicators as Record<string, unknown>;
				}

				applyUpdate(update);
			},
			onError: () => {
				// SSE failed — activate poll fallback
				sseStatus = "error";
				activatePollFallback();
			},
		});

		sseConnection.connect();
		sseStatus = "connecting";

		// Monitor SSE connection status
		const checkInterval = setInterval(() => {
			if (!sseConnection) {
				clearInterval(checkInterval);
				return;
			}
			const newStatus = sseConnection.status;
			if (newStatus !== sseStatus) {
				sseStatus = newStatus;
				if (newStatus === "connected") {
					// SSE recovered — deactivate poll fallback
					deactivatePollFallback();
				} else if (newStatus === "error" || newStatus === "disconnected") {
					activatePollFallback();
				}
			}
		}, 2000);

		// Store interval cleanup reference
		const origDisconnect = sseConnection.disconnect.bind(sseConnection);
		const wrappedConnection = sseConnection;
		wrappedConnection.disconnect = () => {
			clearInterval(checkInterval);
			origDisconnect();
		};
		sseConnection = wrappedConnection;

		resetHeartbeat();
	}

	function stopSSE() {
		clearHeartbeat();
		sseConnection?.disconnect();
		sseConnection = null;
		sseStatus = "disconnected";
	}

	// ── Heartbeat monitoring ────────────────────────────────

	function resetHeartbeat() {
		clearHeartbeat();
		heartbeatTimer = setTimeout(() => {
			// No data received within timeout — SSE may be stale
			if (sseStatus === "connected") {
				sseStatus = "error";
				activatePollFallback();
			}
		}, heartbeatTimeoutMs);
	}

	function clearHeartbeat() {
		if (heartbeatTimer !== undefined) {
			clearTimeout(heartbeatTimer);
			heartbeatTimer = undefined;
		}
	}

	// ── Poll fallback ───────────────────────────────────────

	function activatePollFallback() {
		if (pollActive) return;
		pollActive = true;
		schedulePoll();
	}

	function deactivatePollFallback() {
		pollActive = false;
		stopPolling();
	}

	// ── BatchRiskSummaryOut shape (matches api.d.ts components["schemas"]["BatchRiskSummaryOut"]) ──
	interface BatchRiskSummaryOut {
		profiles: Record<string, CVaRStatus | null>;
		computed_at: string;
		profile_count: number;
	}

	async function fetchAll() {
		if (fetching) return;
		fetching = true;
		try {
			const api = createClientApiClient(getToken);

			// Batch CVaR summary — single request replaces N individual /risk/{p}/cvar calls.
			// Falls back to per-profile calls only if the batch endpoint returns a non-2xx.
			const profilesParam = profileIds.join(",");

			const [batchResult, ...restResults] = await Promise.allSettled([
				api.get<BatchRiskSummaryOut>(`/risk/summary?profiles=${profilesParam}`),
				...profileIds.map((p) => api.get(`/risk/${p}/cvar/history`).catch(() => null)),
				api.get("/risk/regime").catch(() => null),
				api.get("/risk/regime/history").catch(() => null),
				api.get("/analytics/strategy-drift/alerts").catch(() => null),
				api.get("/risk/macro").catch(() => null),
			]);

			const n = profileIds.length;
			// restResults: [history*n, regime, regimeHist, drift, macro]
			const historyResults = restResults.slice(0, n);
			const regimeResult = restResults[n];
			const regimeHistResult = restResults[n + 1];
			const driftResult = restResults[n + 2];
			const macroResult = restResults[n + 3];

			// ── CVaR: prefer batch response; fall back to per-profile if batch failed ──
			const newCvar: Record<string, CVaRStatus> = {};

			if (batchResult?.status === "fulfilled" && batchResult.value) {
				// Batch succeeded — unpack profiles map
				const batch = batchResult.value;
				for (const [p, cvarEntry] of Object.entries(batch.profiles)) {
					if (cvarEntry !== null) {
						newCvar[p] = cvarEntry;
					}
				}
			} else {
				// Batch failed — fall back to individual fetches in parallel
				const fallbackResults = await Promise.allSettled(
					profileIds.map((p) => api.get<CVaRStatus>(`/risk/${p}/cvar`).catch(() => null))
				);
				for (let i = 0; i < n; i++) {
					const p = profileIds[i]!;
					const r = fallbackResults[i];
					if (r?.status === "fulfilled" && r.value) {
						newCvar[p] = r.value as CVaRStatus;
					}
				}
			}

			// ── History ────────────────────────────────────────────────────────
			const newHistory: Record<string, CVaRPoint[]> = {};
			for (let i = 0; i < n; i++) {
				const p = profileIds[i]!;
				const r = historyResults[i];
				if (r?.status === "fulfilled" && r.value) {
					const val = r.value as CVaRPoint[] | { points: CVaRPoint[] };
					newHistory[p] = Array.isArray(val) ? val : val.points ?? [];
				}
			}

			// ── Regime ────────────────────────────────────────────────────────
			const newRegime = (regimeResult?.status === "fulfilled" && regimeResult.value)
				? regimeResult.value as RegimeData
				: undefined;

			let newRegimeHistory: Array<{ date: string; regime: string }> | undefined;
			if (regimeHistResult?.status === "fulfilled" && regimeHistResult.value) {
				const val = regimeHistResult.value as Array<{ date: string; regime: string }> | { history: Array<{ date: string; regime: string }> };
				newRegimeHistory = Array.isArray(val) ? val : val.history ?? [];
			}

			// ── Drift + Macro ─────────────────────────────────────────────────
			const newDrift = (driftResult?.status === "fulfilled" && driftResult.value)
				? driftResult.value as { dtw_alerts: DriftAlert[]; behavior_change_alerts: BehaviorAlert[] }
				: undefined;

			const newMacro = (macroResult?.status === "fulfilled" && macroResult.value)
				? macroResult.value as Record<string, unknown>
				: undefined;

			// Use monotonic version — poll update must pass the gate
			const nextVersion = version + 1;
			applyUpdate({
				version: nextVersion,
				cvarByProfile: newCvar,
				cvarHistoryByProfile: newHistory,
				regime: newRegime,
				regimeHistory: newRegimeHistory,
				driftAlerts: newDrift,
				macroIndicators: newMacro,
			});
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to load risk data";
			status = "error";
			// Auth errors are permanent — stop all retries
			if (e instanceof Error && (e.name === "AuthError" || error.includes("401"))) {
				deactivatePollFallback();
				stopSSE();
			}
		} finally {
			fetching = false;
		}
	}

	function schedulePoll() {
		stopPolling();
		pollTimer = setTimeout(async () => {
			await fetchAll();
			if (pollActive) {
				schedulePoll();
			}
		}, pollingFallbackMs);
	}

	function stopPolling() {
		if (pollTimer !== undefined) {
			clearTimeout(pollTimer);
			pollTimer = undefined;
		}
	}

	// ── Public API ──────────────────────────────────────────

	async function refresh() {
		status = "loading";
		version = 0; // Reset version to accept next update
		await fetchAll();
	}

	function start() {
		// Initial fetch, then start SSE primary
		fetchAll().then(() => {
			startSSE();
		});
	}

	function destroy() {
		stopSSE();
		deactivatePollFallback();
	}

	return {
		get status() { return status; },
		get computedAt() { return computedAt; },
		get nextExpectedUpdate() { return nextExpectedUpdate; },
		get error() { return error; },
		get cvarByProfile() { return cvarByProfile; },
		get cvarHistoryByProfile() { return cvarHistoryByProfile; },
		get regime() { return regime; },
		get regimeHistory() { return regimeHistory; },
		get driftAlerts() { return driftAlerts; },
		get macroIndicators() { return macroIndicators; },
		get connectionQuality(): ConnectionQuality { return getConnectionQuality(); },
		get sseStatus() { return sseStatus; },
		fetchAll,
		refresh,
		start,
		destroy,
		// Legacy compat — callers that used startPolling/stopPolling
		startPolling: start,
		stopPolling: destroy,
	};
}

export type RiskStore = ReturnType<typeof createRiskStore>;
