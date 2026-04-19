/**
 * Wealth Library — preview pane document loader.
 *
 * Phase 5 of the Library frontend (spec §3.4 Fase 5 + §3.6). The
 * loader sits between the URL adapter (selected document id) and
 * the LibraryPreviewPane (renders the appropriate reader). It is
 * single-flight: every new selection aborts the previous fetch
 * before issuing the next, so a fast click between document A and
 * document B can never paint A's contents inside B's pane.
 *
 * Lifecycle hardening
 * -------------------
 * The loader uses two complementary safety nets:
 *
 *  1. `AbortController` per request — last-click-wins on the
 *     network layer. The controller is stored in `current` so any
 *     new `loadDocument(id)` first aborts the previous one.
 *  2. `createMountedGuard()` from @investintell/ui/runtime — even
 *     if a request slips past the abort because the response was
 *     already in flight, the post-await mutation is wrapped in
 *     `guard.guard(...)` so a torn-down loader never writes back
 *     into reactive state. Together they prevent both cross-render
 *     bleed and "setState on unmounted component" warnings.
 *
 * The loader is constructed once per LibraryShell mount via
 * `createPreviewLoader(getToken)`, started inside an $effect.pre,
 * and disposed (`stop` + abort current) in onDestroy.
 */

import {
	createMountedGuard,
	type MountedGuard,
} from "@investintell/ui/runtime";
import { createClientApiClient } from "../../api/client";
import type { LibraryDocumentDetail } from "../../types/library";

export interface PreviewState {
	loading: boolean;
	error: string | null;
	document: LibraryDocumentDetail | null;
	requestedId: string | null;
}

export interface PreviewLoader {
	readonly state: PreviewState;
	loadDocument(id: string | null): Promise<void>;
	clear(): void;
	start(): void;
	dispose(): void;
}

export function createPreviewLoader(
	getToken: () => Promise<string>,
): PreviewLoader {
	const state = $state<PreviewState>({
		loading: false,
		error: null,
		document: null,
		requestedId: null,
	});

	const guard: MountedGuard = createMountedGuard();
	const api = createClientApiClient(getToken);

	let current: AbortController | null = null;

	async function loadDocument(id: string | null): Promise<void> {
		// Cancel any in-flight fetch immediately so the network layer
		// stops chasing the previous document.
		if (current) {
			current.abort();
			current = null;
		}

		if (id === null) {
			// Selection cleared — drop the cached document.
			state.requestedId = null;
			state.document = null;
			state.error = null;
			state.loading = false;
			return;
		}

		const controller = new AbortController();
		current = controller;
		state.requestedId = id;
		state.loading = true;
		state.error = null;

		try {
			const detail = await api.get<LibraryDocumentDetail>(
				`/library/documents/${id}`,
				undefined,
				{ signal: controller.signal },
			);

			// Two layers of safety before we publish:
			//   1. The component must still be mounted (guard).
			//   2. The latest selection must still be this id —
			//      otherwise a slower request finished AFTER a
			//      newer one. Drop the result on the floor.
			guard.guard(() => {
				if (current !== controller) return;
				if (state.requestedId !== id) return;
				state.document = detail;
				state.loading = false;
			});
		} catch (err: unknown) {
			if (err instanceof DOMException && err.name === "AbortError") {
				// Aborted by a newer click — leave state alone, the
				// new request will populate it.
				return;
			}
			guard.guard(() => {
				if (current !== controller) return;
				if (state.requestedId !== id) return;
				state.error =
					err instanceof Error
						? err.message
						: "Failed to load document.";
				state.loading = false;
				state.document = null;
			});
		} finally {
			if (current === controller) {
				current = null;
			}
		}
	}

	function clear(): void {
		if (current) {
			current.abort();
			current = null;
		}
		state.requestedId = null;
		state.document = null;
		state.error = null;
		state.loading = false;
	}

	function start(): void {
		guard.start();
	}

	function dispose(): void {
		guard.stop();
		if (current) {
			current.abort();
			current = null;
		}
	}

	return {
		get state() {
			return state;
		},
		loadDocument,
		clear,
		start,
		dispose,
	};
}
