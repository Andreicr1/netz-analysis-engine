/**
 * Wealth Library — multi-select + Committee Pack bundle builder.
 *
 * Phase 6 of the Library frontend (spec §3.4 Fase 6 + §4.4). Owns
 * the multi-select state for the LibraryTree, the bundle dispatch
 * to `POST /library/bundle`, and the SSE progress stream that
 * surfaces the worker's `generating → uploading → completed` events.
 *
 * The state is exposed through getters so the shell can plug it
 * straight into the LibraryActionBar and LibraryBundleWizard
 * without prop drilling. SSE consumption uses
 * `@investintell/ui`'s `createSSEStream` (fetch + ReadableStream
 * with auth headers — never EventSource per CLAUDE.md).
 */

import { createSSEStream, type SSEConnection } from "@investintell/ui";
import { createClientApiClient } from "$wealth/api/client";

export type BundleStatus =
	| "idle"
	| "dispatching"
	| "generating"
	| "uploading"
	| "completed"
	| "error";

export interface BundleAcceptedResponse {
	bundle_id: string;
	job_id: string;
	sse_channel: string;
	item_count: number;
}

interface BundleProgressEvent {
	event?: string;
	bundle_id?: string;
	step?: string;
	resolved?: number;
	fetched?: number;
	missing?: number;
	size_bytes?: number;
	zip_path?: string;
	manifest_path?: string;
	error?: string;
}

export interface BundleState {
	selected: Set<string>;
	status: BundleStatus;
	bundleId: string | null;
	jobId: string | null;
	step: string | null;
	progressLabel: string;
	error: string | null;
	sizeBytes: number | null;
	fetched: number | null;
	missing: number | null;
}

export interface BundleBuilder {
	readonly state: BundleState;
	readonly canBuild: boolean;
	toggleSelected(libraryIndexId: string): void;
	clearSelection(): void;
	createBundle(): Promise<void>;
	reset(): void;
	dispose(): void;
}

const apiBase =
	import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export function createBundleBuilder(
	getToken: () => Promise<string>,
): BundleBuilder {
	const state = $state<BundleState>({
		selected: new Set<string>(),
		status: "idle",
		bundleId: null,
		jobId: null,
		step: null,
		progressLabel: "",
		error: null,
		sizeBytes: null,
		fetched: null,
		missing: null,
	});

	const api = createClientApiClient(getToken);
	let sse: SSEConnection<BundleProgressEvent> | null = null;

	function toggleSelected(libraryIndexId: string): void {
		const next = new Set(state.selected);
		if (next.has(libraryIndexId)) {
			next.delete(libraryIndexId);
		} else {
			next.add(libraryIndexId);
		}
		state.selected = next;
	}

	function clearSelection(): void {
		state.selected = new Set<string>();
	}

	function reset(): void {
		sse?.disconnect();
		sse = null;
		state.status = "idle";
		state.bundleId = null;
		state.jobId = null;
		state.step = null;
		state.progressLabel = "";
		state.error = null;
		state.sizeBytes = null;
		state.fetched = null;
		state.missing = null;
	}

	function applyEvent(event: BundleProgressEvent): void {
		const type = event.event;
		if (type === "generating") {
			state.status = "generating";
			state.step = event.step ?? null;
			state.progressLabel =
				event.step === "download"
					? `Downloading ${event.resolved ?? 0} entries...`
					: event.step === "zip"
						? `Packing ${event.fetched ?? 0} entries...`
						: "Generating bundle...";
		} else if (type === "uploading") {
			state.status = "uploading";
			state.progressLabel = "Uploading bundle to storage...";
			state.sizeBytes = event.size_bytes ?? null;
		} else if (type === "completed") {
			state.status = "completed";
			state.progressLabel = "Bundle ready.";
			state.sizeBytes = event.size_bytes ?? state.sizeBytes;
			state.fetched = event.fetched ?? null;
			state.missing = event.missing ?? null;
			sse?.disconnect();
			sse = null;
		} else if (type === "error") {
			state.status = "error";
			state.error = event.error ?? "Bundle generation failed.";
			sse?.disconnect();
			sse = null;
		}
	}

	async function createBundle(): Promise<void> {
		if (state.selected.size === 0 || state.status === "dispatching") return;
		reset();
		state.status = "dispatching";

		try {
			const response = await api.post<BundleAcceptedResponse>(
				"/workers/run-library-bundle-builder",
				{
					library_index_ids: Array.from(state.selected),
				},
			);
			// The HTTP trigger returns { status, worker } today; the
			// fully wired endpoint will return bundle_id + job_id.
			// We tolerate both shapes so the wiring lands now and
			// the worker response evolves independently.
			const bundleId =
				(response as unknown as BundleAcceptedResponse).bundle_id ?? null;
			const jobId =
				(response as unknown as BundleAcceptedResponse).job_id ?? null;
			state.bundleId = bundleId;
			state.jobId = jobId;
			state.status = "generating";
			state.progressLabel = "Generation scheduled...";

			if (jobId) {
				sse = createSSEStream<BundleProgressEvent>({
					url: `${apiBase}/jobs/${jobId}/stream`,
					getToken,
					onEvent: applyEvent,
					onError: (err) => {
						state.status = "error";
						state.error = err.message;
					},
				});
				sse.connect();
			}
		} catch (err: unknown) {
			state.status = "error";
			state.error =
				err instanceof Error ? err.message : "Failed to dispatch bundle.";
		}
	}

	function dispose(): void {
		sse?.disconnect();
		sse = null;
	}

	return {
		get state() {
			return state;
		},
		get canBuild() {
			return state.selected.size > 0 && state.status === "idle";
		},
		toggleSelected,
		clearSelection,
		createBundle,
		reset,
		dispose,
	};
}

export function bundleDownloadUrl(bundleId: string): string {
	return `${apiBase}/library/bundle/${bundleId}/download`;
}
