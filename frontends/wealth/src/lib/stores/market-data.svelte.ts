/**
 * Market Data Store — WebSocket-primary, poll-fallback.
 *
 * Manages a WebSocket connection to `/api/v1/market-data/live/ws` for
 * real-time price ticks. Follows the same resilience patterns as
 * risk-store.svelte.ts:
 *   - Heartbeat monitoring (45s timeout)
 *   - Exponential backoff reconnection (1s → 30s cap, max 5 retries)
 *   - Monotonic version counter (prevents stale data overwrites)
 *   - No localStorage (in-memory only)
 *
 * Stability Guardrails (Phase 2 retrofit, §4.1 B1.7–B1.9)
 * -------------------------------------------------------
 * Every incoming price tick used to be written into a reactive
 * `$state` object via `priceMap = { ...priceMap, [t.ticker]: t }`. At
 * the Tiingo IEX firehose rate (hundreds of ticks/sec) this produced
 * one full reactive invalidation per tick — the Dashboard tab froze
 * within minutes (the §7.1 self-DDoS incident).
 *
 * The store now owns a single `createTickBuffer<PriceTick>` configured
 * with `{ intervalMs: 250 }`. Writes go straight into the buffer
 * (`buffer.write(tick)` — one `Map.set` call, no allocation, no
 * reactive invalidation). The buffer's `snapshot` is itself a Svelte
 * 5 `$state(new Map())` and the buffer's internal clock reassigns
 * it exactly once per 250ms, producing four reactive updates per
 * second regardless of tick volume. The store just exposes the
 * snapshot directly through a getter — no mirror, no second timer,
 * no defensive `flush()`.
 *
 * `holdings` is a `$derived` that fuses the static SSR-seeded
 * composition with the live tick snapshot at read time, so consumers
 * keep their existing API (`marketStore.holdings[i].price` is live)
 * without ever touching a spread inside a WS handler.
 *
 * Declared once in (app)/+layout.svelte, shared via Svelte context.
 */

import { createTickBuffer, type TickBuffer } from "@investintell/ui/runtime";

// ── Types ───────────────────────────────────────────────────

export type WsStatus = "connecting" | "connected" | "reconnecting" | "disconnected" | "error";

export interface PriceTick {
	ticker: string;
	price: number;
	change: number;
	change_pct: number;
	volume: number | null;
	aum_usd: number | null;
	timestamp: string;
	source: string;
}

export interface HoldingSummary {
	instrument_id: string;
	ticker: string;
	name: string;
	price: number;
	change: number;
	change_pct: number;
	weight: number;
	aum_usd: number | null;
	asset_class: string;
	currency: string;
}

export interface DashboardSnapshot {
	holdings: HoldingSummary[];
	total_aum: number;
	total_return_pct: number | null;
	as_of: string;
}

interface WsServerMessage {
	type: "price" | "snapshot" | "pong" | "error" | "subscribed";
	data: unknown;
	timestamp: string;
}

export interface MarketDataStoreConfig {
	getToken: () => Promise<string>;
	apiBaseUrl?: string;
	heartbeatTimeoutMs?: number;
}

export interface MarketDataStore {
	// Reactive state (readonly to consumers)
	readonly status: WsStatus;
	/**
	 * Live snapshot of all subscribed tickers, keyed by uppercase
	 * ticker. The underlying `$state` is owned by the tick buffer
	 * and reassigned at most once per 250ms regardless of inbound
	 * tick volume. Consumers read via `priceMap.get(ticker)` —
	 * never `priceMap[ticker]`.
	 */
	readonly priceMap: ReadonlyMap<string, PriceTick>;
	readonly holdings: HoldingSummary[];
	readonly totalAum: number;
	readonly totalReturnPct: number | null;
	readonly asOf: string | null;
	readonly subscribedTickers: string[];
	readonly error: string | null;
	// Actions
	start: () => void;
	stop: () => void;
	/**
	 * Manually re-attempt connection after a permanent error (B1.9).
	 * Resets the retry counter and dispatches a fresh `connect()`. The
	 * store API previously had no escape from the "5 retries → error
	 * forever" terminal state — `reconnect()` is the explicit recovery
	 * lever the UI surfaces in `<svelte:boundary>` failed snippets.
	 */
	reconnect: () => void;
	subscribe: (tickers: string[]) => void;
	unsubscribe: (tickers: string[]) => void;
	seedFromSSR: (snapshot: DashboardSnapshot) => void;
}

// ── Constants ───────────────────────────────────────────────

const BACKOFF_BASE = 1000;
const BACKOFF_MAX = 30_000;
const MAX_RETRIES = 5;
const DEFAULT_HEARTBEAT_TIMEOUT = 45_000;
// Tabular UI cadence — 4 updates/sec, legible without "slot machine".
// Aligned with the design spec §3.1 default for Dashboard surfaces.
const TICK_FLUSH_INTERVAL_MS = 250;
// Hard ceiling on simultaneously-tracked tickers. The screener catalog
// page-size cap (200) is the upper bound the user can drive into the
// buffer in one frame; 5000 leaves headroom for cross-page navigation
// without dropping fresh data on the floor.
const TICK_BUFFER_MAX_KEYS = 5000;

// ── Store Factory ───────────────────────────────────────────

export function createMarketDataStore(config: MarketDataStoreConfig): MarketDataStore {
	const {
		getToken,
		apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1",
		heartbeatTimeoutMs = DEFAULT_HEARTBEAT_TIMEOUT,
	} = config;

	// ── Reactive state ──────────────────────────────────────
	let status = $state<WsStatus>("disconnected");

	// SSR-seeded portfolio composition. Updated only by seedFromSSR —
	// never per WebSocket tick. Live prices fold in via the `holdings`
	// derived below.
	let rawHoldings = $state<HoldingSummary[]>([]);

	let totalAum = $state(0);
	let asOf = $state<string | null>(null);
	let subscribedTickers = $state<string[]>([]);
	let error = $state<string | null>(null);

	// ── Tick buffer ────────────────────────────────────────
	// All inbound price ticks land here. The buffer owns its own
	// reactive snapshot (`$state(new Map())`) and reassigns it on
	// its internal 250ms clock — Svelte 5 propagates the change to
	// every dependent `$derived` and template binding without any
	// external mirror or polling.
	const tickBuffer: TickBuffer<PriceTick> = createTickBuffer<PriceTick>({
		keyOf: (t) => t.ticker.toUpperCase(),
		clock: { intervalMs: TICK_FLUSH_INTERVAL_MS },
		maxKeys: TICK_BUFFER_MAX_KEYS,
		evictionPolicy: "drop_oldest",
	});

	// Live-fused holdings. Reads from `rawHoldings` (reactive) and
	// `tickBuffer.snapshot` (reactive, owned by the buffer) so this
	// re-runs once per buffer flush, not once per tick. Returns the
	// same object reference for unchanged rows so downstream
	// `{#each}` blocks don't churn DOM nodes.
	const holdings = $derived.by((): HoldingSummary[] => {
		if (rawHoldings.length === 0) return rawHoldings;
		const snap = tickBuffer.snapshot;
		if (snap.size === 0) return rawHoldings;
		return rawHoldings.map((h) => {
			const key = (h.ticker || "").toUpperCase();
			if (!key) return h;
			const tick = snap.get(key);
			if (!tick) return h;
			return {
				...h,
				price: tick.price,
				change: tick.change,
				change_pct: tick.change_pct,
				aum_usd: tick.aum_usd ?? h.aum_usd,
			};
		});
	});

	const totalReturnPct = $derived.by((): number | null => {
		if (holdings.length === 0) return null;
		return holdings.reduce((sum, h) => sum + h.change_pct * h.weight, 0);
	});

	// ── Internal state ──────────────────────────────────────
	let ws: WebSocket | null = null;
	let retryCount = 0;
	let heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let version = 0; // Monotonic — prevents stale overwrites
	// Set, not array — dedup is O(1) and `pendingTickers` cannot grow
	// linearly with subscribe/unsubscribe churn (B1.8).
	const pendingTickers = new Set<string>();

	// ── Heartbeat ───────────────────────────────────────────

	function resetHeartbeat() {
		if (heartbeatTimer) clearTimeout(heartbeatTimer);
		heartbeatTimer = setTimeout(() => {
			if (status === "connected") {
				// No heartbeat/pong received — reconnect
				ws?.close();
				scheduleReconnect();
			}
		}, heartbeatTimeoutMs);
	}

	function clearHeartbeat() {
		if (heartbeatTimer) {
			clearTimeout(heartbeatTimer);
			heartbeatTimer = null;
		}
	}

	// ── Reconnection ────────────────────────────────────────

	function scheduleReconnect() {
		if (retryCount >= MAX_RETRIES) {
			status = "error";
			error = `WebSocket reconnection failed after ${MAX_RETRIES} retries`;
			return;
		}

		status = "reconnecting";
		const delay = Math.min(BACKOFF_BASE * 2 ** retryCount, BACKOFF_MAX);
		retryCount++;

		reconnectTimer = setTimeout(() => {
			connect();
		}, delay);
	}

	function clearReconnect() {
		if (reconnectTimer) {
			clearTimeout(reconnectTimer);
			reconnectTimer = null;
		}
	}

	// ── Message handling ────────────────────────────────────

	function handleMessage(msg: WsServerMessage) {
		resetHeartbeat();
		version++;

		switch (msg.type) {
			case "price": {
				const tick = msg.data as PriceTick;
				if (tick?.ticker) {
					// Single non-blocking write into the coalescing
					// buffer. No spread, no allocation, no reactive
					// invalidation — the snapshot mirror picks it up
					// on the next flush tick.
					tickBuffer.write(tick);
				}
				break;
			}
			case "subscribed": {
				const data = msg.data as { tickers: string[] };
				subscribedTickers = data?.tickers ?? [];
				break;
			}
			case "pong":
				// Heartbeat response — already handled by resetHeartbeat()
				break;
			case "error": {
				const data = msg.data as { message?: string };
				error = data?.message ?? "Unknown server error";
				break;
			}
		}
	}

	// ── Connect ─────────────────────────────────────────────

	async function connect() {
		if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
			return; // Already connected
		}

		status = "connecting";
		error = null;

		let token: string;
		try {
			token = await getToken();
		} catch {
			status = "error";
			error = "Failed to retrieve auth token";
			return;
		}

		// Preflight: verify backend is reachable before opening WebSocket.
		// Avoids noisy browser console errors when backend is down.
		try {
			const healthUrl = apiBaseUrl.replace(/\/api\/v1$/, "") + "/health";
			const health = await fetch(healthUrl, {
				signal: AbortSignal.timeout(3000),
			});
			if (!health.ok) throw new Error("unhealthy");
		} catch {
			scheduleReconnect();
			return;
		}

		// Build WS URL: http→ws, https→wss
		const wsBase = apiBaseUrl.replace(/^http/, "ws");
		const url = `${wsBase}/market-data/live/ws?token=${encodeURIComponent(token)}`;

		try {
			ws = new WebSocket(url);
		} catch {
			scheduleReconnect();
			return;
		}

		ws.onopen = () => {
			status = "connected";
			retryCount = 0;
			error = null;
			resetHeartbeat();

			// Subscribe to pending tickers
			if (pendingTickers.size > 0) {
				sendSubscribe(Array.from(pendingTickers));
			}
		};

		ws.onmessage = (event) => {
			try {
				const msg = JSON.parse(event.data) as WsServerMessage;
				handleMessage(msg);
			} catch {
				// Ignore unparseable messages
			}
		};

		ws.onerror = () => {
			// onclose will fire next — handle reconnect there
		};

		ws.onclose = (event) => {
			clearHeartbeat();
			ws = null;

			if (event.code === 1008) {
				// Auth failure — do not reconnect
				status = "error";
				error = "Authentication failed";
				return;
			}

			if (status !== "disconnected") {
				scheduleReconnect();
			}
		};
	}

	// ── Send helpers ────────────────────────────────────────

	function sendSubscribe(tickers: string[]) {
		if (ws?.readyState === WebSocket.OPEN) {
			ws.send(JSON.stringify({ action: "subscribe", tickers }));
		}
	}

	function sendUnsubscribe(tickers: string[]) {
		if (ws?.readyState === WebSocket.OPEN) {
			ws.send(JSON.stringify({ action: "unsubscribe", tickers }));
		}
	}

	// ── Public API ──────────────────────────────────────────

	function start() {
		retryCount = 0;
		connect();
	}

	function stop() {
		status = "disconnected";
		clearHeartbeat();
		clearReconnect();
		// Release the buffer's clock + visibility listener. The buffer
		// is single-use after `dispose()`; the store instance is
		// created once per layout mount and `stop()` runs on layout
		// teardown, so this is the correct lifecycle moment.
		tickBuffer.dispose();
		if (ws) {
			ws.onclose = null; // Prevent reconnect on intentional close
			ws.close(1000, "Client disconnected");
			ws = null;
		}
	}

	function reconnect() {
		// Recover from terminal "error" state — caller (typically a
		// `<svelte:boundary>` failed snippet) decided the user wants
		// another attempt. Clear the timers, reset the budget, fire
		// off a fresh connect. The tick buffer is still alive (we
		// only dispose it on `stop()`), so no buffer state needs
		// rebuilding here.
		clearReconnect();
		clearHeartbeat();
		retryCount = 0;
		error = null;
		status = "disconnected";
		connect();
	}

	function subscribeTickers(tickers: string[]) {
		const upper = tickers.map((t) => t.toUpperCase()).filter((t) => t.length > 0);
		for (const t of upper) pendingTickers.add(t);
		sendSubscribe(upper);
	}

	function unsubscribeTickers(tickers: string[]) {
		const upper = tickers.map((t) => t.toUpperCase()).filter((t) => t.length > 0);
		for (const t of upper) pendingTickers.delete(t);
		sendUnsubscribe(upper);
	}

	function seedFromSSR(snapshot: DashboardSnapshot) {
		rawHoldings = snapshot.holdings;
		totalAum = snapshot.total_aum;
		asOf = snapshot.as_of;

		// Seed the buffer with the SSR prices so the first frame the
		// user sees is correct even before the WebSocket warms up.
		// `writeMany` performs one Map.set per ticker; the buffer's
		// own clock will publish the resulting snapshot on the next
		// flush tick. We force a single immediate `flush()` here so
		// the SSR-rendered Dashboard does not flash empty between
		// hydration and the first 250 ms tick.
		const seedTicks: PriceTick[] = [];
		for (const h of snapshot.holdings) {
			if (!h.ticker) continue;
			seedTicks.push({
				ticker: h.ticker,
				price: h.price,
				change: h.change,
				change_pct: h.change_pct,
				volume: null,
				aum_usd: h.aum_usd,
				timestamp: snapshot.as_of,
				source: "ssr",
			});
		}
		if (seedTicks.length > 0) {
			tickBuffer.writeMany(seedTicks);
			tickBuffer.flush();
		}

		// Auto-subscribe to all holding tickers
		pendingTickers.clear();
		for (const h of snapshot.holdings) {
			if (h.ticker) pendingTickers.add(h.ticker.toUpperCase());
		}
	}

	return {
		get status() { return status; },
		get priceMap() { return tickBuffer.snapshot; },
		get holdings() { return holdings; },
		get totalAum() { return totalAum; },
		get totalReturnPct() { return totalReturnPct; },
		get asOf() { return asOf; },
		get subscribedTickers() { return subscribedTickers; },
		get error() { return error; },
		start,
		stop,
		reconnect,
		subscribe: subscribeTickers,
		unsubscribe: unsubscribeTickers,
		seedFromSSR,
	};
}
