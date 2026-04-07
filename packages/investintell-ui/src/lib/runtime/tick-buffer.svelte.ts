/**
 * Tick buffer — high-frequency event coalescer.
 *
 * Stability Guardrails §3.1 — satisfies P1 (Bounded), P2 (Batched),
 * P4 (Lifecycle).
 *
 * Problem this solves
 * -------------------
 * The legacy wealth market-data store wrote every incoming WebSocket
 * price tick directly into a reactive `$state` object via spread:
 *
 *     priceMap = { ...priceMap, [tick.ticker]: tick };
 *     holdings = [...holdings];
 *
 * With the Tiingo IEX firehose emitting hundreds of ticks per second
 * per ticker, this pattern produces hundreds of reactive invalidations
 * per second. Svelte 5 re-runs every `$derived` and re-renders every
 * dependent component on each assignment, producing a self-DDoS: the
 * browser never finishes one frame before the next batch arrives,
 * memory churn is continuous, and the Dashboard tab freezes or OOMs
 * within minutes. This is the mechanical root cause of the §7.1
 * incident in the design spec.
 *
 * `createTickBuffer<T>()` is the mandatory primitive for any source
 * that emits more than ~10 events per second. It coalesces writes
 * per key into a single internal `Map` and flushes a snapshot to a
 * reactive `$state` on a clock (requestAnimationFrame for animated
 * surfaces, `setInterval` for tabular displays at a human-legible
 * cadence). The snapshot is owned by this primitive — consumers
 * just read `buffer.snapshot` and Svelte's reactive graph picks up
 * the change automatically. No external mirror, no defensive
 * `flush()`, no second timer.
 *
 * What this primitive guarantees
 * ------------------------------
 * - **Non-blocking `write()`.** Every write is a single `Map.set`
 *   call. No spread, no allocation per tick, no reactive invalidation.
 * - **One reactive update per flush.** The internal snapshot is a
 *   Svelte 5 `$state(new Map())` and is reassigned exactly once per
 *   clock tick. At `intervalMs: 250` (Dashboard default), 500
 *   writes/sec become 4 updates/sec — legible for humans and
 *   non-pathological for the browser. Consumers reading
 *   `buffer.snapshot` from inside a Svelte component (or a `.svelte.ts`
 *   store) get reactivity for free; no external `$state` mirror or
 *   defensive `flush()` polling is needed.
 * - **Hard key cap.** `maxKeys` is enforced; when exceeded, the
 *   configured `evictionPolicy` removes either the oldest or the
 *   newest entry. `dropped` counter exposes the pressure.
 * - **Tab visibility awareness.** When the tab is hidden, the flush
 *   timer is paused but `write()` continues to merge into the
 *   internal Map (bounded by `maxKeys`). When the tab becomes
 *   visible, a synchronous flush fires immediately and the clock
 *   resumes. This kills the "tab unhides → browser chews through
 *   50 000 queued updates at once" failure mode.
 * - **Explicit lifecycle.** `dispose()` cancels the clock, removes
 *   listeners, and empties the Map. Lint rule
 *   `require-tick-buffer-dispose` (ESLint plugin, commit 11) enforces
 *   this is called in `onDestroy`.
 *
 * Non-goals (v1)
 * --------------
 * - No per-key TTL. Keys persist in the snapshot until they are
 *   overwritten by `write()` or evicted by `maxKeys`.
 * - No derivation beyond the raw snapshot Map. Consumers derive
 *   their own `$derived` views from the exposed snapshot.
 */

// tick-buffer is a shared primitive: it owns its reactive snapshot
// state via Svelte 5 runes (`$state`). The `.svelte.ts` extension
// is what unlocks rune support in non-component files; the file is
// still safe to import from vitest because Svelte 5's $state proxy
// works in plain JS contexts when the test runner enables runes
// (the @investintell/ui vitest config does so via the svelte-vite
// plugin). Browser globals (`requestAnimationFrame`, `document`)
// are required for the visibility-aware clock and are gracefully
// no-op'd under SSR.

export interface TickBufferConfig<T> {
	/** Extracts the dedup key from an item. Last write wins per key. */
	keyOf: (item: T) => string;
	/** Hard cap on distinct keys held in memory (P1). */
	maxKeys?: number;
	/** How to evict when `maxKeys` is exceeded. Default: drop_oldest. */
	evictionPolicy?: "drop_oldest" | "drop_newest";
	/**
	 * Clock source.
	 *
	 * - `"raf"` → `requestAnimationFrame` (~16 ms). Appropriate for
	 *   animated surfaces (sparklines, canvas charts).
	 * - `{ intervalMs: N }` → `setInterval(N)` / `setTimeout`.
	 *   Appropriate for tabular displays; `250 ms` is the Dashboard
	 *   default (4 updates/sec — legible without "slot machine").
	 *
	 * Default: `"raf"`.
	 */
	clock?: "raf" | { intervalMs: number };
}

export interface TickBuffer<T> {
	/** Reactive snapshot — changes once per flush. */
	readonly snapshot: ReadonlyMap<string, T>;
	/** Total items dropped since creation due to `maxKeys` overflow. */
	readonly dropped: number;
	/** Total items written since creation (including drops). */
	readonly written: number;
	/** Non-blocking write. Never throws, never awaits. */
	write(item: T): void;
	/** Bulk write. */
	writeMany(items: Iterable<T>): void;
	/** Pause flushes. Writes still accumulate (up to `maxKeys`). */
	pause(): void;
	/** Resume flushes. Flushes immediately if there are pending writes. */
	resume(): void;
	/** Force an immediate flush (copy internal map into snapshot). */
	flush(): void;
	/** Release all resources. MUST be called in `onDestroy`. */
	dispose(): void;
}

interface RafLike {
	requestAnimationFrame(cb: FrameRequestCallback): number;
	cancelAnimationFrame(handle: number): void;
}

/**
 * Create a new tick buffer.
 *
 * The returned object exposes a reactive `snapshot` getter backed
 * by a Svelte 5 `$state(new Map())`. Reading `buffer.snapshot` from
 * inside a `$derived`, `$effect`, or component template is enough
 * — when the clock fires `flush()` and reassigns the internal
 * `$state`, the dependent reactive node re-runs automatically.
 */
export function createTickBuffer<T>(config: TickBufferConfig<T>): TickBuffer<T> {
	const keyOf = config.keyOf;
	const maxKeys = config.maxKeys ?? Number.POSITIVE_INFINITY;
	const evictionPolicy = config.evictionPolicy ?? "drop_oldest";
	const clock = config.clock ?? "raf";

	if (maxKeys <= 0) {
		throw new Error("TickBufferConfig.maxKeys must be > 0 when set");
	}

	const internal = new Map<string, T>();
	// Reactive snapshot — owned by the buffer. The .svelte.ts file
	// extension authorises the use of Svelte 5 runes here. Reassigning
	// `snapshot = new Map(internal)` is what propagates the new map
	// reference through every dependent `$derived`, `$effect`, and
	// template binding.
	let snapshot = $state<Map<string, T>>(new Map());
	let dirty = false;
	let dropped = 0;
	let written = 0;
	let paused = false;
	let disposed = false;

	let rafHandle: number | null = null;
	let intervalHandle: ReturnType<typeof setInterval> | null = null;
	let visibilityListener: (() => void) | null = null;

	function flush(): void {
		if (!dirty) return;
		snapshot = new Map(internal);
		dirty = false;
	}

	function scheduleRaf(): void {
		if (disposed || paused) return;
		const raf = globalThis as unknown as RafLike;
		if (rafHandle !== null) return;
		rafHandle = raf.requestAnimationFrame(() => {
			rafHandle = null;
			if (disposed || paused) return;
			flush();
			if (dirty) scheduleRaf();
		});
	}

	function startInterval(ms: number): void {
		if (disposed || paused) return;
		if (intervalHandle !== null) return;
		intervalHandle = setInterval(() => {
			if (disposed || paused) return;
			flush();
		}, ms);
	}

	function stopInterval(): void {
		if (intervalHandle !== null) {
			clearInterval(intervalHandle);
			intervalHandle = null;
		}
	}

	function stopRaf(): void {
		if (rafHandle !== null) {
			const raf = globalThis as unknown as RafLike;
			raf.cancelAnimationFrame(rafHandle);
			rafHandle = null;
		}
	}

	function startClock(): void {
		if (clock === "raf") {
			if (dirty) scheduleRaf();
		} else {
			startInterval(clock.intervalMs);
		}
	}

	function stopClock(): void {
		stopRaf();
		stopInterval();
	}

	function handleVisibilityChange(): void {
		if (disposed) return;
		const doc = (globalThis as unknown as { document?: Document }).document;
		if (!doc) return;
		if (doc.visibilityState === "hidden") {
			paused = true;
			stopClock();
		} else {
			paused = false;
			// Immediate catch-up flush.
			flush();
			startClock();
		}
	}

	// Attach visibility listener if we have a document.
	const doc = (globalThis as unknown as { document?: Document }).document;
	if (doc && typeof doc.addEventListener === "function") {
		visibilityListener = handleVisibilityChange;
		doc.addEventListener("visibilitychange", visibilityListener);
		// Reflect initial state.
		if (doc.visibilityState === "hidden") paused = true;
	}

	// Start the clock on creation; only writes drive the raf path,
	// but intervals start immediately so idle buffers still flush
	// their final state.
	if (clock !== "raf") startClock();

	function write(item: T): void {
		if (disposed) return;
		written += 1;
		const key = keyOf(item);
		if (internal.has(key)) {
			internal.set(key, item);
			dirty = true;
			if (clock === "raf" && !paused) scheduleRaf();
			return;
		}
		if (internal.size >= maxKeys) {
			if (evictionPolicy === "drop_newest") {
				dropped += 1;
				return;
			}
			// drop_oldest: Map preserves insertion order.
			const oldestKey = internal.keys().next().value as string | undefined;
			if (oldestKey !== undefined) {
				internal.delete(oldestKey);
				dropped += 1;
			}
		}
		internal.set(key, item);
		dirty = true;
		if (clock === "raf" && !paused) scheduleRaf();
	}

	function writeMany(items: Iterable<T>): void {
		for (const item of items) write(item);
	}

	function pause(): void {
		paused = true;
		stopClock();
	}

	function resume(): void {
		if (disposed) return;
		paused = false;
		flush();
		startClock();
	}

	function dispose(): void {
		if (disposed) return;
		disposed = true;
		stopClock();
		if (visibilityListener && doc) {
			doc.removeEventListener("visibilitychange", visibilityListener);
			visibilityListener = null;
		}
		internal.clear();
		snapshot = new Map();
		dirty = false;
	}

	return {
		get snapshot() {
			return snapshot;
		},
		get dropped() {
			return dropped;
		},
		get written() {
			return written;
		},
		write,
		writeMany,
		pause,
		resume,
		flush,
		dispose,
	};
}
