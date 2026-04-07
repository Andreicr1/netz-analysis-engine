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
 * Declared once in (app)/+layout.svelte, shared via Svelte context.
 */

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
	readonly priceMap: Record<string, PriceTick>;
	readonly holdings: HoldingSummary[];
	readonly totalAum: number;
	readonly totalReturnPct: number | null;
	readonly asOf: string | null;
	readonly subscribedTickers: string[];
	readonly error: string | null;
	// Actions
	start: () => void;
	stop: () => void;
	subscribe: (tickers: string[]) => void;
	unsubscribe: (tickers: string[]) => void;
	seedFromSSR: (snapshot: DashboardSnapshot) => void;
}

// ── Constants ───────────────────────────────────────────────

const BACKOFF_BASE = 1000;
const BACKOFF_MAX = 30_000;
const MAX_RETRIES = 5;
const DEFAULT_HEARTBEAT_TIMEOUT = 45_000;

// ── Store Factory ───────────────────────────────────────────

export function createMarketDataStore(config: MarketDataStoreConfig): MarketDataStore {
	const {
		getToken,
		apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1",
		heartbeatTimeoutMs = DEFAULT_HEARTBEAT_TIMEOUT,
	} = config;

	// ── Reactive state ──────────────────────────────────────
	let status = $state<WsStatus>("disconnected");
	let priceMap = $state<Record<string, PriceTick>>({});
	let holdings = $state<HoldingSummary[]>([]);
	let totalAum = $state(0);
	let totalReturnPct = $derived.by(() => {
		if (holdings.length === 0) return null;
		return holdings.reduce((sum, h) => sum + (h.change_pct * h.weight), 0);
	});
	let asOf = $state<string | null>(null);
	let subscribedTickers = $state<string[]>([]);
	let error = $state<string | null>(null);

	// ── Internal state ──────────────────────────────────────
	let ws: WebSocket | null = null;
	let retryCount = 0;
	let heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let version = 0; // Monotonic — prevents stale overwrites
	let pendingTickers: string[] = []; // Tickers to subscribe after connect

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
					priceMap = { ...priceMap, [tick.ticker]: tick };
					// Update matching holding in-place
					const idx = holdings.findIndex((h) => h.ticker === tick.ticker);
					if (idx >= 0) {
						const updated = [...holdings];
						const existing = updated[idx]!;
						updated[idx] = {
							...existing,
							price: tick.price,
							change: tick.change,
							change_pct: tick.change_pct,
							aum_usd: tick.aum_usd ?? existing.aum_usd,
						};
						holdings = updated;
					}
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
			const healthUrl = apiBaseUrl.replace(/\/api\/v1$/, '') + '/health';
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
			if (pendingTickers.length > 0) {
				sendSubscribe(pendingTickers);
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
		if (ws) {
			ws.onclose = null; // Prevent reconnect on intentional close
			ws.close(1000, "Client disconnected");
			ws = null;
		}
	}

	function subscribeTickers(tickers: string[]) {
		const upper = tickers.map((t) => t.toUpperCase());
		pendingTickers = [...new Set([...pendingTickers, ...upper])];
		sendSubscribe(upper);
	}

	function unsubscribeTickers(tickers: string[]) {
		const upper = tickers.map((t) => t.toUpperCase());
		pendingTickers = pendingTickers.filter((t) => !upper.includes(t));
		sendUnsubscribe(upper);
	}

	function seedFromSSR(snapshot: DashboardSnapshot) {
		holdings = snapshot.holdings;
		totalAum = snapshot.total_aum;
		asOf = snapshot.as_of;

		// Build initial priceMap from holdings
		const map: Record<string, PriceTick> = {};
		for (const h of snapshot.holdings) {
			if (h.ticker) {
				map[h.ticker] = {
					ticker: h.ticker,
					price: h.price,
					change: h.change,
					change_pct: h.change_pct,
					volume: null,
					aum_usd: h.aum_usd,
					timestamp: snapshot.as_of,
					source: "ssr",
				};
			}
		}
		priceMap = map;

		// Auto-subscribe to all holding tickers
		pendingTickers = snapshot.holdings.map((h) => h.ticker).filter(Boolean);
	}

	return {
		get status() { return status; },
		get priceMap() { return priceMap; },
		get holdings() { return holdings; },
		get totalAum() { return totalAum; },
		get totalReturnPct() { return totalReturnPct; },
		get asOf() { return asOf; },
		get subscribedTickers() { return subscribedTickers; },
		get error() { return error; },
		start,
		stop,
		subscribe: subscribeTickers,
		unsubscribe: unsubscribeTickers,
		seedFromSSR,
	};
}
