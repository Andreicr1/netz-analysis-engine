/**
 * Screener import client — Phase 4 (§4.3) frontend half.
 *
 * Handles the protocol for the unified screener import:
 *   1. Compute a stable Idempotency-Key (sha256 of identifier+block_id)
 *      so a double-click within the server-side TTL window receives
 *      the same job_id back.
 *   2. POST /screener/import/{identifier} with the header.
 *   3. Receive 202 { job_id, identifier, status: "queued" } from the
 *      enqueue endpoint, OR a cached identical payload from the
 *      @idempotent decorator on a repeat click.
 *   4. Open /jobs/{job_id}/stream via fetch + ReadableStream (NOT
 *      EventSource — we need the Authorization header) and surface
 *      progress events to the caller.
 *
 * Returns a `runScreenerImport()` async function that yields a
 * `ScreenerImportRun` object whose state evolves as the SSE channel
 * fires events. Components consume the run by awaiting `result()` for
 * the terminal value or subscribing to the live `progress` reactive
 * snapshot.
 */

import { createClientApiClient } from "$lib/api/client";

export type ImportPhase =
	| "queued"
	| "validating"
	| "resolving_sec"
	| "writing"
	| "done"
	| "error";

export interface ImportProgress {
	phase: ImportPhase;
	pct: number;
	message?: string;
}

export interface ImportSuccessResult {
	instrument_id: string;
	name: string;
	identifier: string;
	status: "imported" | "linked" | "already_in_org";
	source: "esma" | "sec";
}

export interface ImportErrorResult {
	code: string;
	message: string;
	recoverable: boolean;
}

export interface ScreenerImportOptions {
	identifier: string;
	blockId?: string | null;
	strategy?: string | null;
	getToken: () => Promise<string>;
	apiBaseUrl?: string;
	/** Called on every progress tick. */
	onProgress?: (p: ImportProgress) => void;
}

export interface ScreenerImportRun {
	/** Job id assigned by the backend. */
	jobId: string;
	/** Identifier the server normalized (uppercase). */
	identifier: string;
	/** Resolves with the success payload, throws on error. */
	result: () => Promise<ImportSuccessResult>;
}

const PHASE_PCT: Record<ImportPhase, number> = {
	queued: 0,
	validating: 5,
	resolving_sec: 25,
	writing: 75,
	done: 100,
	error: 100,
};

/**
 * SHA-256 hex digest of the input string. Uses the Web Crypto API
 * which is available in every modern browser; falls back to a
 * deterministic non-cryptographic key if SubtleCrypto is unavailable
 * (older Safari, very old SSR contexts) so the import path never
 * fails on hashing alone.
 */
async function sha256Hex(input: string): Promise<string> {
	const subtle = globalThis.crypto?.subtle;
	if (subtle) {
		const buf = new TextEncoder().encode(input);
		const digest = await subtle.digest("SHA-256", buf);
		return Array.from(new Uint8Array(digest))
			.map((b) => b.toString(16).padStart(2, "0"))
			.join("");
	}
	// Fallback: deterministic non-crypto fold. Good enough for
	// idempotency dedup; the server still namespaces by org_id.
	let h1 = 0xdeadbeef;
	let h2 = 0x41c6ce57;
	for (let i = 0; i < input.length; i++) {
		const ch = input.charCodeAt(i);
		h1 = Math.imul(h1 ^ ch, 2654435761);
		h2 = Math.imul(h2 ^ ch, 1597334677);
	}
	return (h1 >>> 0).toString(16).padStart(8, "0") +
		(h2 >>> 0).toString(16).padStart(8, "0");
}

/**
 * Compute the Idempotency-Key the server expects on the
 * /screener/import/{identifier} endpoint. The server prepends the
 * caller's organization_id, so the client only needs to namespace
 * by the payload (identifier + block_id) — two clients in different
 * orgs cannot collide.
 */
export async function computeImportIdempotencyKey(
	identifier: string,
	blockId: string | null | undefined,
): Promise<string> {
	const normalized = `${identifier.trim().toUpperCase()}|${blockId ?? ""}`;
	return await sha256Hex(normalized);
}

/**
 * Enqueue an import and stream progress to ``onProgress``. Resolves
 * with a ``ScreenerImportRun`` whose ``result()`` awaits the terminal
 * SSE event.
 *
 * The run handle is intentionally split: the caller can update its
 * UI state on the synchronous return (job is queued, show a spinner)
 * and then ``await run.result()`` separately to get the
 * instrument_id once the worker finishes.
 */
export async function runScreenerImport(
	options: ScreenerImportOptions,
): Promise<ScreenerImportRun> {
	const {
		identifier,
		blockId = null,
		strategy = null,
		getToken,
		apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1",
		onProgress,
	} = options;

	const idemKey = await computeImportIdempotencyKey(identifier, blockId);
	const api = createClientApiClient(getToken);

	type EnqueueResponse = {
		job_id: string;
		identifier: string;
		status: string;
	};

	const enqueue = await api.post<EnqueueResponse>(
		`/screener/import/${encodeURIComponent(identifier)}`,
		{ block_id: blockId, strategy },
		{ headers: { "Idempotency-Key": idemKey } },
	);

	onProgress?.({ phase: "queued", pct: PHASE_PCT.queued });

	const resultPromise = consumeJobStream(
		enqueue.job_id,
		apiBaseUrl,
		getToken,
		onProgress,
	);

	return {
		jobId: enqueue.job_id,
		identifier: enqueue.identifier,
		result: () => resultPromise,
	};
}

/**
 * Open the job SSE channel and resolve with the terminal payload.
 *
 * The SSE event format is the one published by ``publish_event`` in
 * ``backend/app/core/jobs/tracker.py``: each frame is a JSON object
 * with at least an ``event`` field plus arbitrary payload keys
 * merged at the top level.
 */
async function consumeJobStream(
	jobId: string,
	apiBaseUrl: string,
	getToken: () => Promise<string>,
	onProgress?: (p: ImportProgress) => void,
): Promise<ImportSuccessResult> {
	const token = await getToken();
	const response = await fetch(
		`${apiBaseUrl}/jobs/${encodeURIComponent(jobId)}/stream`,
		{
			headers: {
				Authorization: `Bearer ${token}`,
				Accept: "text/event-stream",
			},
		},
	);

	if (!response.ok || !response.body) {
		// SSE failed to open — fall back to the status polling endpoint
		// so a fully-finished job (cached idempotent response) still
		// resolves correctly.
		return await pollJobStatus(jobId, apiBaseUrl, getToken);
	}

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";

	try {
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;
			buffer += decoder.decode(value, { stream: true });
			const frames = buffer.split("\n\n");
			buffer = frames.pop() ?? "";

			for (const frame of frames) {
				const dataLine = frame
					.split("\n")
					.find((line) => line.startsWith("data: "));
				if (!dataLine) continue;
				const payload = parseSseFrame(dataLine.slice(6));
				if (!payload) continue;

				const eventName = (payload.event ?? "") as string;

				if (eventName === "progress") {
					const phase = (payload.step as ImportPhase | undefined) ?? "queued";
					const pct = typeof payload.pct === "number"
						? payload.pct
						: PHASE_PCT[phase] ?? 0;
					onProgress?.({
						phase,
						pct,
						message: payload.message as string | undefined,
					});
				} else if (eventName === "done") {
					onProgress?.({ phase: "done", pct: 100 });
					const result = payload.result as ImportSuccessResult | undefined;
					if (result) return result;
					throw new Error("Import done event missing result payload");
				} else if (eventName === "error") {
					onProgress?.({
						phase: "error",
						pct: 100,
						message: (payload.message as string | undefined) ?? "Import failed",
					});
					const err = payload as unknown as ImportErrorResult;
					throw new ScreenerImportError(err);
				}
			}
		}
	} finally {
		try {
			await reader.cancel();
		} catch {
			// best-effort
		}
	}

	// Stream closed without a terminal event — fall back to status poll.
	return await pollJobStatus(jobId, apiBaseUrl, getToken);
}

/**
 * Fallback when SSE drops before delivering a terminal event. The
 * backend persists terminal state via ``persist_job_state``; the
 * /jobs/{id}/status endpoint surfaces it.
 */
async function pollJobStatus(
	jobId: string,
	apiBaseUrl: string,
	getToken: () => Promise<string>,
): Promise<ImportSuccessResult> {
	const token = await getToken();
	const res = await fetch(
		`${apiBaseUrl}/jobs/${encodeURIComponent(jobId)}/status`,
		{
			headers: { Authorization: `Bearer ${token}` },
			signal: AbortSignal.timeout(8000),
		},
	);
	if (!res.ok) {
		throw new Error(`Job status poll failed: HTTP ${res.status}`);
	}
	const state = await res.json();
	if (state.terminal_state === "success" || state.terminal_state === "degraded") {
		// The success payload is not in the persisted state; the SSE
		// stream is the canonical source. Reconstruct a minimal stub
		// so the caller knows the import landed.
		return {
			instrument_id: "",
			name: "",
			identifier: "",
			status: "imported",
			source: "sec",
		};
	}
	throw new ScreenerImportError({
		code: "FAILED",
		message: state.errors?.[0] ?? "Job failed without details",
		recoverable: state.retryable ?? false,
	});
}

function parseSseFrame(raw: string): Record<string, unknown> | null {
	try {
		return JSON.parse(raw) as Record<string, unknown>;
	} catch {
		return null;
	}
}

export class ScreenerImportError extends Error {
	readonly code: string;
	readonly recoverable: boolean;

	constructor(detail: ImportErrorResult) {
		super(detail.message);
		this.name = "ScreenerImportError";
		this.code = detail.code;
		this.recoverable = detail.recoverable;
	}
}
