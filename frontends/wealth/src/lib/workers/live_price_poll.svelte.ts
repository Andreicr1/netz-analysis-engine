/**
 * live_price_poll — Phase 9 Block C mock live price feed.
 *
 * A lightweight in-process polling manager that emits a synthetic
 * price tick every ~1.5s via ``setInterval``. It is NOT a real Web
 * Worker — Web Workers would complicate the Svelte 5 reactivity
 * bridge (postMessage → store → effect) for a mock feed that costs
 * microseconds per tick. A future blocker (Phase 9 Block D or the
 * original plan's Phase 9 Task 9.1 ``live_price_poll`` backend
 * worker) will replace this module with an SSE bridge to the real
 * Yahoo batch quote poller. The consumer-side contract stays the
 * same: a reactive ``ticks`` buffer + ``start`` / ``stop`` lifecycle.
 *
 * Random walk:
 *   Gaussian-ish (Box-Muller) shocks scaled to ±0.05% std dev on
 *   each tick, around an anchored base price. Produces a visually
 *   plausible curve at 1.5s cadence without catastrophic drift.
 *
 * Sliding window:
 *   Last ``BUFFER_SIZE`` ticks (60 by default). New arrays are
 *   assigned on every tick so Svelte 5 ``$state`` tracks the
 *   mutation. Down-stream consumers (WorkbenchCoreChart,
 *   SparklineSVG inside LivePortfolioKpiStrip) slice or consume
 *   the full buffer as needed.
 *
 * Lifecycle rules (LiveWorkbenchShell enforces these via ``$effect``):
 *   - start() only when the overview tool is active AND a live
 *     portfolio is selected
 *   - stop() when the tool changes, the portfolio deselects, or
 *     the shell unmounts
 *   - reset() when switching portfolios (wipes buffer, seeds fresh
 *     base price)
 */

export interface PriceTick {
	/** Epoch milliseconds when the tick was generated. */
	ts: number;
	/** Synthetic price (no currency — relative to the base). */
	price: number;
}

export const LIVE_PRICE_BUFFER_SIZE = 60;
export const LIVE_PRICE_SPARKLINE_SLICE = 20;
const DEFAULT_INTERVAL_MS = 1500;
const DEFAULT_BASE_PRICE = 100;
const RANDOM_WALK_STD = 0.0005; // 0.05% per-tick std

export interface LivePricePollerOptions {
	basePrice?: number;
	intervalMs?: number;
}

/**
 * Random-walk price poller with a Svelte-reactive sliding buffer.
 *
 * The ``ticks`` field is declared with ``$state`` so Svelte tracks
 * mutations automatically — consumers can read ``poller.ticks``
 * inside ``$derived`` / ``$effect`` / templates and reactivity
 * works through the field access.
 */
export class LivePricePoller {
	/** Sliding window of the last ``LIVE_PRICE_BUFFER_SIZE`` ticks. */
	ticks = $state<PriceTick[]>([]);

	private intervalId: ReturnType<typeof setInterval> | null = null;
	private basePrice: number;
	private lastPrice: number;
	private readonly intervalMs: number;

	constructor(opts: LivePricePollerOptions = {}) {
		this.basePrice = opts.basePrice ?? DEFAULT_BASE_PRICE;
		this.lastPrice = this.basePrice;
		this.intervalMs = opts.intervalMs ?? DEFAULT_INTERVAL_MS;
	}

	get isRunning(): boolean {
		return this.intervalId !== null;
	}

	/**
	 * Start emitting ticks. Idempotent — a second call while running
	 * is a no-op so the shell's ``$effect`` can safely re-invoke on
	 * dependency changes without tearing down the interval.
	 */
	start(): void {
		if (this.intervalId !== null) return;
		// Seed the buffer with the opening price so charts never
		// start with an empty polyline and the sparkline has at
		// least one point to render immediately.
		const now = Date.now();
		this.ticks = [{ ts: now, price: this.lastPrice }];
		this.intervalId = setInterval(() => this.tick(), this.intervalMs);
	}

	/** Stop the interval and clear the buffer. Safe to call twice. */
	stop(): void {
		if (this.intervalId !== null) {
			clearInterval(this.intervalId);
			this.intervalId = null;
		}
		this.ticks = [];
		this.lastPrice = this.basePrice;
	}

	/**
	 * Re-anchor the random walk to a new base price. Used when the
	 * shell switches between live portfolios — each portfolio gets
	 * its own visual opening price so the chart does not carry over
	 * the previous series.
	 */
	reset(newBasePrice?: number): void {
		const wasRunning = this.isRunning;
		this.stop();
		if (newBasePrice !== undefined) {
			this.basePrice = newBasePrice;
		}
		this.lastPrice = this.basePrice;
		if (wasRunning) this.start();
	}

	private tick(): void {
		// Box-Muller transform for a smoother Gaussian shock than
		// ``Math.random() - 0.5`` uniform noise. Clamp u1 away from
		// 0 to avoid ``log(0)`` = -Infinity.
		const u1 = Math.max(Math.random(), 1e-9);
		const u2 = Math.random();
		const gauss = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
		const shock = this.lastPrice * RANDOM_WALK_STD * gauss;
		this.lastPrice = Math.max(0.01, this.lastPrice + shock);

		const entry: PriceTick = { ts: Date.now(), price: this.lastPrice };
		// Slide the window: create a new array reference so ``$state``
		// tracks the mutation. ``slice(1)`` drops the oldest entry once
		// the buffer is full.
		const next =
			this.ticks.length >= LIVE_PRICE_BUFFER_SIZE
				? [...this.ticks.slice(1), entry]
				: [...this.ticks, entry];
		this.ticks = next;
	}
}
