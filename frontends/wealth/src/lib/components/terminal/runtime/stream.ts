/**
 * createTerminalStream — unified SSE runtime primitive for (terminal)/.
 * ====================================================================
 *
 * Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md
 *   §Appendix G (runtime/stream.ts), §2 rule 7 (no browser-native SSE API).
 *
 * Every streaming surface inside (terminal)/ — construction runs, live
 * prices, alerts, drift events, macro flashes — consumes this factory.
 * One primitive, one reconnect policy, one SSR contract.
 *
 * Why handroll SSE framing? The browser-native SSE API cannot carry
 * custom headers, and Clerk JWT must travel in the Authorization
 * header. We use fetch() + ReadableStream and parse SSE frames by
 * hand so auth headers ride along.
 *
 * Why not @investintell/ui's createSSEStream? That one is a
 * Svelte-aware runes-based helper that accumulates events into a
 * $state array. The terminal runtime needs a leaner, framework-free
 * factory whose handle is safe to hold inside a $effect closure
 * without creating a reactive dependency on every incoming frame.
 */

export interface TerminalStreamOptions<T> {
	url: string;
	onMessage: (event: T) => void;
	onError?: (error: Error) => void;
	onOpen?: () => void;
	onClose?: () => void;
	headers?: Record<string, string>;
	signal?: AbortSignal;
	reconnect?: boolean;
	maxReconnectDelayMs?: number;
	initialReconnectDelayMs?: number;
}

export type TerminalStreamStatus = "connecting" | "open" | "closed" | "error";

export interface TerminalStreamHandle {
	readonly status: TerminalStreamStatus;
	readonly lastEventAt: number | null;
	close(): void;
}

const DEFAULT_INITIAL_DELAY = 1_000;
const DEFAULT_MAX_DELAY = 30_000;
const JITTER_SPREAD_MS = 400;

/**
 * Build a terminal SSE handle. On the server the factory returns a
 * frozen no-op handle so callers can invoke it from a component body
 * without guarding on `typeof window`; the real connection is mounted
 * by the caller's $effect on the client.
 */
export function createTerminalStream<T>(
	options: TerminalStreamOptions<T>,
): TerminalStreamHandle {
	if (typeof window === "undefined") {
		return Object.freeze({
			get status(): TerminalStreamStatus {
				return "closed";
			},
			get lastEventAt(): number | null {
				return null;
			},
			close() {
				/* no-op on server */
			},
		});
	}

	const reconnectEnabled = options.reconnect !== false;
	const initialDelayMs = options.initialReconnectDelayMs ?? DEFAULT_INITIAL_DELAY;
	const maxDelayMs = options.maxReconnectDelayMs ?? DEFAULT_MAX_DELAY;

	let status: TerminalStreamStatus = "connecting";
	let lastEventAt: number | null = null;
	let reconnectAttempt = 0;
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let abortController: AbortController | null = null;
	let explicitlyClosed = false;

	const upstreamSignal = options.signal;
	const upstreamAbortHandler = () => {
		explicitlyClosed = true;
		teardown();
		status = "closed";
	};
	if (upstreamSignal) {
		if (upstreamSignal.aborted) {
			explicitlyClosed = true;
			status = "closed";
			return Object.freeze({
				get status() {
					return status;
				},
				get lastEventAt() {
					return lastEventAt;
				},
				close() {
					/* already closed */
				},
			});
		}
		upstreamSignal.addEventListener("abort", upstreamAbortHandler, { once: true });
	}

	function teardown() {
		if (reconnectTimer !== null) {
			clearTimeout(reconnectTimer);
			reconnectTimer = null;
		}
		if (abortController !== null) {
			abortController.abort();
			abortController = null;
		}
	}

	function dispatchError(err: unknown) {
		if (explicitlyClosed) return;
		const wrapped =
			err instanceof Error ? err : new Error(typeof err === "string" ? err : "stream error");
		status = "error";
		try {
			options.onError?.(wrapped);
		} catch {
			/* swallow consumer errors so the stream does not crash the page */
		}
	}

	function scheduleReconnect() {
		if (!reconnectEnabled || explicitlyClosed) {
			status = "closed";
			try {
				options.onClose?.();
			} catch {
				/* swallow */
			}
			return;
		}
		/* exponential backoff — see Stability Guardrails P6 fault-tolerant principle */
		const base = Math.min(initialDelayMs * Math.pow(2, reconnectAttempt), maxDelayMs);
		const jitter = (Math.random() - 0.5) * JITTER_SPREAD_MS;
		const delay = Math.max(0, base + jitter);
		reconnectAttempt += 1;
		status = "connecting";
		reconnectTimer = setTimeout(() => {
			reconnectTimer = null;
			void connect();
		}, delay);
	}

	async function connect() {
		if (explicitlyClosed) return;
		abortController = new AbortController();

		const headers: Record<string, string> = {
			Accept: "text/event-stream",
			...(options.headers ?? {}),
		};

		try {
			const response = await fetch(options.url, {
				method: "GET",
				headers,
				credentials: "include",
				signal: abortController.signal,
			});

			if (!response.ok) {
				throw new Error(`stream http ${response.status}`);
			}
			if (!response.body) {
				throw new Error("stream missing body");
			}

			status = "open";
			reconnectAttempt = 0;
			try {
				options.onOpen?.();
			} catch {
				/* swallow */
			}

			const reader = response.body.getReader();
			const decoder = new TextDecoder("utf-8");
			let buffer = "";

			while (true) {
				const { value, done } = await reader.read();
				if (done) break;
				buffer += decoder.decode(value, { stream: true });
				buffer = drainFrames(buffer);
			}

			// Stream closed by server — attempt reconnect unless caller closed us.
			if (!explicitlyClosed) {
				scheduleReconnect();
			} else {
				status = "closed";
			}
		} catch (err) {
			if (explicitlyClosed) {
				status = "closed";
				return;
			}
			if ((err as { name?: string })?.name === "AbortError") {
				status = "closed";
				return;
			}
			dispatchError(err);
			scheduleReconnect();
		}
	}

	function drainFrames(buffer: string): string {
		let remaining = buffer;
		while (true) {
			const terminator = remaining.indexOf("\n\n");
			if (terminator === -1) return remaining;
			const frame = remaining.slice(0, terminator);
			remaining = remaining.slice(terminator + 2);
			handleFrame(frame);
		}
	}

	function handleFrame(frame: string) {
		if (frame.length === 0) return;
		const lines = frame.split(/\r?\n/);
		const dataLines: string[] = [];
		for (const line of lines) {
			if (line.length === 0) continue;
			if (line.startsWith(":")) continue; // comment / heartbeat
			if (line.startsWith("data:")) {
				dataLines.push(line.slice(5).replace(/^\s/, ""));
			}
			// `event:` / `id:` / `retry:` are tolerated but ignored; the
			// terminal runtime carries event type inside the JSON payload.
		}
		if (dataLines.length === 0) return;
		const raw = dataLines.join("\n");
		let parsed: T;
		try {
			parsed = JSON.parse(raw) as T;
		} catch (err) {
			dispatchError(err);
			return;
		}
		lastEventAt = Date.now();
		try {
			options.onMessage(parsed);
		} catch (err) {
			dispatchError(err);
		}
	}

	void connect();

	const handle: TerminalStreamHandle = Object.freeze({
		get status() {
			return status;
		},
		get lastEventAt() {
			return lastEventAt;
		},
		close() {
			if (explicitlyClosed) return;
			explicitlyClosed = true;
			teardown();
			if (upstreamSignal) {
				upstreamSignal.removeEventListener("abort", upstreamAbortHandler);
			}
			status = "closed";
			try {
				options.onClose?.();
			} catch {
				/* swallow */
			}
		},
	});

	return handle;
}
