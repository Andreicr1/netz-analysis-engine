/**
 * TradingView Advanced Charting Library — Custom Datafeed Adapter.
 *
 * Bridges the Netz market-data API to the TradingView widget:
 *   - REST:  GET /api/v1/market-data/historical/{ticker}  (OHLCV bars)
 *   - WS:    /api/v1/market-data/live/ws?token=<jwt>       (real-time ticks)
 *
 * Implements the IBasicDataFeed interface expected by the widget.
 * All console.log calls are intentional — tactical debugging for
 * first-iteration integration. Remove once stable.
 *
 * Reference: https://www.tradingview.com/charting-library-docs/
 */

// ── Resolution helpers ──────────────────────────────────────────────

/** Map TradingView resolution strings to our API interval param. */
function resolutionToInterval(resolution: string): string {
	switch (resolution) {
		case "1": return "1min";
		case "5": return "5min";
		case "15": return "15min";
		case "30": return "30min";
		case "60": return "1hour";
		case "240": return "4hour";
		case "1D":
		case "D": return "daily";
		default: return "daily";
	}
}

/** Convert ISO-8601 timestamp to UNIX seconds. */
function isoToUnix(iso: string): number {
	return Math.floor(new Date(iso).getTime() / 1000);
}

// ── Types (TradingView Charting Library interfaces) ─────────────────

interface DatafeedConfiguration {
	supported_resolutions: string[];
	exchanges: { value: string; name: string; desc: string }[];
	symbols_types: { name: string; value: string }[];
}

interface LibrarySymbolInfo {
	name: string;
	full_name: string;
	description: string;
	type: string;
	session: string;
	timezone: string;
	exchange: string;
	listed_exchange: string;
	format: string;
	minmov: number;
	pricescale: number;
	has_intraday: boolean;
	has_daily: boolean;
	has_weekly_and_monthly: boolean;
	supported_resolutions: string[];
	volume_precision: number;
	data_status: string;
}

interface Bar {
	time: number;   // ms since epoch
	open: number;
	high: number;
	low: number;
	close: number;
	volume?: number;
}

interface SubscribeBarsCallback {
	(bar: Bar): void;
}

// ── WebSocket real-time subscription manager ────────────────────────

interface WsSubscription {
	ticker: string;
	resolution: string;
	callback: SubscribeBarsCallback;
	lastBar: Bar | null;
}

class RealtimeManager {
	private ws: WebSocket | null = null;
	private subscriptions = new Map<string, WsSubscription>();
	private wsUrl: string;
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private isConnecting = false;

	constructor(wsUrl: string) {
		this.wsUrl = wsUrl;
	}

	subscribe(
		subscriberUID: string,
		ticker: string,
		resolution: string,
		callback: SubscribeBarsCallback,
		lastBar: Bar | null,
	): void {
		console.log(`[tv-datafeed] subscribeBars: ${ticker} (${resolution}) uid=${subscriberUID}`);
		this.subscriptions.set(subscriberUID, {
			ticker: ticker.toUpperCase(),
			resolution,
			callback,
			lastBar,
		});
		this.ensureConnected();
		this.sendSubscribe(ticker);
	}

	unsubscribe(subscriberUID: string): void {
		const sub = this.subscriptions.get(subscriberUID);
		if (sub) {
			console.log(`[tv-datafeed] unsubscribeBars: ${sub.ticker} uid=${subscriberUID}`);
			this.subscriptions.delete(subscriberUID);
			// Check if any other subscription still needs this ticker
			const stillNeeded = [...this.subscriptions.values()].some(
				(s) => s.ticker === sub.ticker,
			);
			if (!stillNeeded) {
				this.sendUnsubscribe(sub.ticker);
			}
		}
	}

	destroy(): void {
		if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
		this.subscriptions.clear();
		if (this.ws) {
			this.ws.close(1000, "destroy");
			this.ws = null;
		}
	}

	private ensureConnected(): void {
		if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
		if (this.isConnecting) return;
		this.connect();
	}

	private connect(): void {
		if (this.isConnecting) return;
		this.isConnecting = true;

		console.log("[tv-datafeed] WS connecting:", this.wsUrl);
		const ws = new WebSocket(this.wsUrl);

		ws.onopen = () => {
			console.log("[tv-datafeed] WS connected");
			this.ws = ws;
			this.isConnecting = false;
			// Re-subscribe all active tickers
			const tickers = new Set(
				[...this.subscriptions.values()].map((s) => s.ticker),
			);
			if (tickers.size > 0) {
				ws.send(JSON.stringify({
					action: "subscribe",
					tickers: [...tickers],
				}));
			}
		};

		ws.onmessage = (event) => {
			try {
				const msg = JSON.parse(event.data);
				if (msg.type === "price" && msg.data) {
					this.handlePriceTick(msg.data);
				}
			} catch {
				// Ignore parse errors
			}
		};

		ws.onclose = () => {
			console.log("[tv-datafeed] WS disconnected, reconnecting in 3s...");
			this.ws = null;
			this.isConnecting = false;
			if (this.subscriptions.size > 0) {
				this.reconnectTimer = setTimeout(() => this.connect(), 3000);
			}
		};

		ws.onerror = () => {
			console.warn("[tv-datafeed] WS error");
			this.isConnecting = false;
		};
	}

	private sendSubscribe(ticker: string): void {
		if (this.ws?.readyState === WebSocket.OPEN) {
			this.ws.send(JSON.stringify({
				action: "subscribe",
				tickers: [ticker.toUpperCase()],
			}));
		}
	}

	private sendUnsubscribe(ticker: string): void {
		if (this.ws?.readyState === WebSocket.OPEN) {
			this.ws.send(JSON.stringify({
				action: "unsubscribe",
				tickers: [ticker.toUpperCase()],
			}));
		}
	}

	/**
	 * Handle a real-time price tick from the WebSocket.
	 * Tick shape from our Tiingo bridge:
	 *   { ticker: "SPY", last: 523.45, timestamp: "2026-04-09T15:30:00Z", ... }
	 */
	private handlePriceTick(data: Record<string, unknown>): void {
		const tickerRaw = (data.ticker as string)?.toUpperCase();
		const price = Number(data.last ?? data.close ?? data.price ?? 0);
		const timestamp = data.timestamp as string | undefined;

		if (!tickerRaw || !price) return;

		const tickTimeMs = timestamp ? new Date(timestamp).getTime() : Date.now();

		for (const sub of this.subscriptions.values()) {
			if (sub.ticker !== tickerRaw) continue;

			const last = sub.lastBar;
			if (!last) {
				// No previous bar — create one from the tick
				const bar: Bar = {
					time: tickTimeMs,
					open: price,
					high: price,
					low: price,
					close: price,
					volume: 0,
				};
				sub.lastBar = bar;
				sub.callback(bar);
				continue;
			}

			// Check if tick belongs to current bar or starts a new one
			const barDurationMs = resolutionToMs(sub.resolution);
			const barStart = Math.floor(last.time / barDurationMs) * barDurationMs;
			const tickBarStart = Math.floor(tickTimeMs / barDurationMs) * barDurationMs;

			if (tickBarStart > barStart) {
				// New bar
				const bar: Bar = {
					time: tickBarStart,
					open: price,
					high: price,
					low: price,
					close: price,
					volume: 0,
				};
				sub.lastBar = bar;
				sub.callback(bar);
			} else {
				// Update current bar
				last.close = price;
				last.high = Math.max(last.high, price);
				last.low = Math.min(last.low, price);
				sub.callback({ ...last });
			}
		}
	}
}

function resolutionToMs(resolution: string): number {
	switch (resolution) {
		case "1": return 60_000;
		case "5": return 5 * 60_000;
		case "15": return 15 * 60_000;
		case "30": return 30 * 60_000;
		case "60": return 60 * 60_000;
		case "240": return 4 * 60 * 60_000;
		case "1D":
		case "D": return 24 * 60 * 60_000;
		default: return 24 * 60 * 60_000;
	}
}

// ── Main Datafeed Class ─────────────────────────────────────────────

export interface NetzDatafeedOptions {
	/** Base URL for REST API (e.g. "/api/v1/market-data"). */
	apiBaseUrl: string;
	/** Full WebSocket URL (e.g. "wss://api.investintell.com/api/v1/market-data/live/ws?token=xxx"). */
	wsUrl: string;
}

/**
 * Custom Datafeed for TradingView Advanced Charting Library.
 *
 * Usage:
 *   const datafeed = createNetzDatafeed({ apiBaseUrl: "/api/v1/market-data", wsUrl: "..." });
 *   new TradingView.widget({ datafeed, ... });
 */
export function createNetzDatafeed(options: NetzDatafeedOptions) {
	const { apiBaseUrl, wsUrl } = options;
	const realtimeManager = new RealtimeManager(wsUrl);

	const SUPPORTED_RESOLUTIONS = ["1", "5", "15", "30", "60", "240", "1D"];

	return {
		// ── onReady ──────────────────────────────────────────────
		onReady(callback: (config: DatafeedConfiguration) => void): void {
			console.log("[tv-datafeed] onReady");
			// TradingView requires this to be async (setTimeout)
			setTimeout(() => {
				callback({
					supported_resolutions: SUPPORTED_RESOLUTIONS,
					exchanges: [
						{ value: "", name: "All Exchanges", desc: "" },
						{ value: "US", name: "US Markets", desc: "" },
					],
					symbols_types: [
						{ name: "All types", value: "" },
						{ name: "ETF", value: "etf" },
						{ name: "Fund", value: "fund" },
						{ name: "Stock", value: "stock" },
					],
				});
			}, 0);
		},

		// ── searchSymbols ────────────────────────────────────────
		searchSymbols(
			userInput: string,
			_exchange: string,
			_symbolType: string,
			onResult: (results: Array<{
				symbol: string;
				full_name: string;
				description: string;
				exchange: string;
				type: string;
			}>) => void,
		): void {
			console.log("[tv-datafeed] searchSymbols:", userInput);
			// Minimal implementation — symbols are pre-known from the portfolio
			onResult([]);
		},

		// ── resolveSymbol ────────────────────────────────────────
		resolveSymbol(
			symbolName: string,
			onResolve: (info: LibrarySymbolInfo) => void,
			onError: (reason: string) => void,
		): void {
			console.log("[tv-datafeed] resolveSymbol:", symbolName);
			const ticker = symbolName.toUpperCase();

			setTimeout(() => {
				const symbolInfo: LibrarySymbolInfo = {
					name: ticker,
					full_name: ticker,
					description: ticker,
					type: "fund",
					session: "0930-1600",
					timezone: "America/New_York",
					exchange: "US",
					listed_exchange: "US",
					format: "price",
					minmov: 1,
					pricescale: 100,
					has_intraday: true,
					has_daily: true,
					has_weekly_and_monthly: false,
					supported_resolutions: SUPPORTED_RESOLUTIONS,
					volume_precision: 0,
					data_status: "streaming",
				};
				onResolve(symbolInfo);
			}, 0);
		},

		// ── getBars ──────────────────────────────────────────────
		async getBars(
			symbolInfo: LibrarySymbolInfo,
			resolution: string,
			periodParams: { from: number; to: number; countBack?: number; firstDataRequest?: boolean },
			onResult: (bars: Bar[], meta: { noData: boolean }) => void,
			onError: (reason: string) => void,
		): Promise<void> {
			const ticker = symbolInfo.name;
			const interval = resolutionToInterval(resolution);
			const startDate = new Date(periodParams.from * 1000).toISOString().split("T")[0];
			const endDate = new Date(periodParams.to * 1000).toISOString().split("T")[0];

			console.log(
				`[tv-datafeed] getBars: ${ticker} ${interval} ${startDate}→${endDate}`,
			);

			try {
				const url = `${apiBaseUrl}/historical/${encodeURIComponent(ticker)}`
					+ `?interval=${interval}&start_date=${startDate}&end_date=${endDate}`;

				const resp = await fetch(url);
				if (!resp.ok) {
					console.warn(`[tv-datafeed] getBars HTTP ${resp.status}`);
					onResult([], { noData: true });
					return;
				}

				const data = await resp.json();
				const rawBars: Array<{
					timestamp: string;
					open: number;
					high: number;
					low: number;
					close: number;
					volume: number;
				}> = data.bars ?? [];

				if (rawBars.length === 0) {
					console.log("[tv-datafeed] getBars: no data");
					onResult([], { noData: true });
					return;
				}

				const bars: Bar[] = rawBars.map((b) => ({
					time: isoToUnix(b.timestamp) * 1000, // TV expects ms
					open: Number(b.open),
					high: Number(b.high),
					low: Number(b.low),
					close: Number(b.close),
					volume: Number(b.volume ?? 0),
				}));

				// Sort ascending by time (TradingView requirement)
				bars.sort((a, b) => a.time - b.time);

				console.log(
					`[tv-datafeed] getBars: ${bars.length} bars, first=${new Date(bars[0]!.time).toISOString()}, last=${new Date(bars[bars.length - 1]!.time).toISOString()}`,
				);

				onResult(bars, { noData: false });
			} catch (err) {
				console.error("[tv-datafeed] getBars error:", err);
				onError(String(err));
			}
		},

		// ── subscribeBars ────────────────────────────────────────
		subscribeBars(
			symbolInfo: LibrarySymbolInfo,
			resolution: string,
			onTick: SubscribeBarsCallback,
			subscriberUID: string,
			_onResetCacheNeededCallback: () => void,
		): void {
			realtimeManager.subscribe(
				subscriberUID,
				symbolInfo.name,
				resolution,
				onTick,
				null,
			);
		},

		// ── unsubscribeBars ──────────────────────────────────────
		unsubscribeBars(subscriberUID: string): void {
			realtimeManager.unsubscribe(subscriberUID);
		},

		// ── Cleanup (call on component destroy) ──────────────────
		destroy(): void {
			console.log("[tv-datafeed] destroy");
			realtimeManager.destroy();
		},
	};
}

export type NetzDatafeed = ReturnType<typeof createNetzDatafeed>;
