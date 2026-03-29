/**
 * Reactive polling utility with $effect cleanup.
 *
 * Usage:
 *   const poller = createPoller({
 *     fn: () => api.get(`/jobs/${jobId}`),
 *     intervalMs: 5000,
 *     maxDurationMs: 300_000,
 *     shouldStop: (r) => r.status === "completed" || r.status === "failed",
 *   });
 *   // poller.result, poller.error, poller.stop()
 */

export interface PollerConfig<T> {
	fn: () => Promise<T>;
	intervalMs: number;
	maxDurationMs?: number;
	shouldStop?: (result: T) => boolean;
}

export interface PollerState<T> {
	readonly result: T | null;
	readonly error: string | null;
	readonly active: boolean;
	stop: () => void;
}

export function createPoller<T>(config: PollerConfig<T>): PollerState<T> {
	let result = $state<T | null>(null);
	let error = $state<string | null>(null);
	let active = $state(true);
	let timer: ReturnType<typeof setTimeout> | null = null;
	let maxTimer: ReturnType<typeof setTimeout> | null = null;

	const { fn, intervalMs, maxDurationMs = 300_000, shouldStop } = config;

	function stop() {
		active = false;
		if (timer) clearTimeout(timer);
		if (maxTimer) clearTimeout(maxTimer);
		timer = null;
		maxTimer = null;
	}

	async function poll() {
		if (!active) return;
		try {
			const res = await fn();
			result = res;
			error = null;
			if (shouldStop?.(res)) {
				stop();
				return;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : "Polling failed";
		}
		if (active) {
			timer = setTimeout(poll, intervalMs);
		}
	}

	// Start immediately
	poll();

	// Max duration guard
	maxTimer = setTimeout(() => {
		if (active) {
			error = "Polling timed out";
			stop();
		}
	}, maxDurationMs);

	return {
		get result() { return result; },
		get error() { return error; },
		get active() { return active; },
		stop,
	};
}
