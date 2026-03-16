/** SSE client using fetch + ReadableStream (NOT EventSource — needs auth headers). */

import type { NetzApiClient } from "./api-client.js";

export type SSEStatus = "connecting" | "connected" | "disconnected" | "error";

export interface SSEEvent {
	type?: string;
	data: unknown;
}

export interface SSEConfig<T> {
	url: string;
	getToken: () => Promise<string>;
	onEvent: (event: T) => void;
	onError?: (error: Error) => void;
	initialState?: T[];
}

export interface SSEConnection<T> {
	connect: () => void;
	disconnect: () => void;
	events: T[];
	status: SSEStatus;
	error: Error | null;
}

const BACKOFF_BASE = 1000;
const BACKOFF_MAX = 30000;
const MAX_RETRIES = 5;
const HEARTBEAT_TIMEOUT = 45000;

export function createSSEStream<T>(config: SSEConfig<T>): SSEConnection<T> {
	let status: SSEStatus = $state("disconnected");
	let error: Error | null = $state(null);
	// Cap events to prevent unbounded memory growth (#097).
	// Consumers should use onEvent callback for real-time processing.
	const MAX_EVENTS = 200;
	let events: T[] = $state(config.initialState ? [...config.initialState] : []);

	let abortController: AbortController | null = null;
	let retryCount = 0;
	let heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

	function resetHeartbeat() {
		if (heartbeatTimer) clearTimeout(heartbeatTimer);
		heartbeatTimer = setTimeout(() => {
			// No heartbeat received — reconnect
			if (status === "connected") {
				abortController?.abort();
				scheduleReconnect();
			}
		}, HEARTBEAT_TIMEOUT);
	}

	function scheduleReconnect() {
		if (retryCount >= MAX_RETRIES) {
			status = "error";
			error = new Error(`SSE reconnection failed after ${MAX_RETRIES} retries`);
			config.onError?.(error);
			return;
		}
		const delay = Math.min(BACKOFF_BASE * Math.pow(2, retryCount), BACKOFF_MAX);
		retryCount++;
		status = "connecting";
		reconnectTimer = setTimeout(() => connect(), delay);
	}

	async function connect() {
		disconnect();
		status = "connecting";
		error = null;
		abortController = new AbortController();

		try {
			const token = await config.getToken();
			const res = await fetch(config.url, {
				headers: {
					Authorization: `Bearer ${token}`,
					Accept: "text/event-stream",
				},
				signal: abortController.signal,
			});

			if (!res.ok) {
				throw new Error(`SSE connection failed: ${res.status}`);
			}

			if (!res.body) {
				throw new Error("SSE response has no body");
			}

			status = "connected";
			retryCount = 0;
			resetHeartbeat();

			const reader = res.body.getReader();
			const decoder = new TextDecoder();
			let buffer = "";

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				resetHeartbeat();
				buffer += decoder.decode(value, { stream: true });

				const lines = buffer.split("\n");
				// Keep incomplete last line in buffer
				buffer = lines.pop() ?? "";

				let currentData = "";
				for (const line of lines) {
					if (line.startsWith("data: ")) {
						currentData += line.slice(6);
					} else if (line === "" && currentData) {
						// End of event
						try {
							const parsed = JSON.parse(currentData) as T;
							if (events.length >= MAX_EVENTS) {
								events.splice(0, events.length - MAX_EVENTS + 1);
							}
							events.push(parsed);
							config.onEvent(parsed);
						} catch {
							// Skip malformed events
						}
						currentData = "";
					}
				}
			}

			// Stream ended normally — reconnect
			if (status === "connected") {
				scheduleReconnect();
			}
		} catch (err) {
			if ((err as Error).name === "AbortError") return;
			error = err instanceof Error ? err : new Error(String(err));
			config.onError?.(error);
			scheduleReconnect();
		}
	}

	function disconnect() {
		abortController?.abort();
		abortController = null;
		if (heartbeatTimer) clearTimeout(heartbeatTimer);
		if (reconnectTimer) clearTimeout(reconnectTimer);
		heartbeatTimer = null;
		reconnectTimer = null;
		status = "disconnected";
	}

	return {
		connect,
		disconnect,
		get events() { return events; },
		get status() { return status; },
		get error() { return error; },
	};
}

// ── Subscribe-then-Snapshot ─────────────────────────────────────
// Eliminates event gaps: SSE subscribes first, REST loads snapshot,
// buffered events merge on top of snapshot, then live tail continues.

export interface SSESnapshotConfig<T> {
	sseUrl: string;
	restUrl: string;
	apiClient: NetzApiClient;
	getToken: () => Promise<string>;
	/** Merge REST snapshot with buffered SSE events received during REST call. */
	merge: (snapshot: T, buffered: SSEEvent[]) => T;
}

export interface SSESnapshotConnection<T> {
	readonly state: T | null;
	readonly status: SSEStatus;
	readonly error: Error | null;
	connect: () => Promise<void>;
	disconnect: () => void;
}

/**
 * Subscribe-then-snapshot pattern for SSE + REST data loading.
 *
 * 1. Connect SSE first (events buffer while REST loads)
 * 2. Call REST endpoint for current state (snapshot)
 * 3. Merge: snapshot is base, buffer has events from the gap
 * 4. Continue with live SSE tail
 */
export function createSSEWithSnapshot<T>(config: SSESnapshotConfig<T>): SSESnapshotConnection<T> {
	let state: T | null = $state(null);
	let sseStatus: SSEStatus = $state("disconnected");
	let sseError: Error | null = $state(null);

	const buffer: SSEEvent[] = [];
	let snapshotLoaded = false;
	let innerSSE: SSEConnection<SSEEvent> | null = null;

	async function connect() {
		snapshotLoaded = false;
		buffer.length = 0;
		sseStatus = "connecting";
		sseError = null;

		// Step 1: Subscribe SSE first — events buffer while REST loads
		innerSSE = createSSEStream<SSEEvent>({
			url: config.sseUrl,
			getToken: config.getToken,
			onEvent: (event) => {
				if (!snapshotLoaded) {
					buffer.push(event);
				} else {
					// Live tail: merge single event into state
					state = config.merge(state as T, [event]);
				}
			},
			onError: (err) => {
				sseError = err;
			},
		});
		innerSSE.connect();

		try {
			// Step 2: REST snapshot (current state)
			const snapshot = await config.apiClient.get<T>(config.restUrl);

			// Step 3: Merge snapshot with buffered events from the gap
			state = config.merge(snapshot, [...buffer]);
			snapshotLoaded = true;
			buffer.length = 0;
			sseStatus = "connected";
		} catch (err) {
			sseError = err instanceof Error ? err : new Error(String(err));
			sseStatus = "error";
		}
	}

	function disconnect() {
		innerSSE?.disconnect();
		innerSSE = null;
		snapshotLoaded = false;
		buffer.length = 0;
		sseStatus = "disconnected";
	}

	return {
		get state() { return state; },
		get status() { return sseStatus; },
		get error() { return sseError; },
		connect,
		disconnect,
	};
}
