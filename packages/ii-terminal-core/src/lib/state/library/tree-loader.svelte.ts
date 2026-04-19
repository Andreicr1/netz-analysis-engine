/**
 * Wealth Library — tree state and lazy children loader.
 *
 * Phase 3 of the Library frontend (spec §3.4 / §3.6). This module
 * is the single source of truth for *expansion* + *children fetching*
 * inside the LibraryTree. It deliberately stays small and dumb:
 *
 *   * The L1 + L2 roots come pre-loaded from `GET /library/tree`
 *     (server loader → page data) so the very first render is
 *     instant. The state module never re-fetches the tree itself.
 *   * When the user expands an L2 (or deeper) folder we hit
 *     `GET /library/folders/{path}/children` and store the result
 *     under the encoded path key.
 *   * Concurrent expand→collapse→expand cycles can race the
 *     network. We track an `AbortController` per path so the
 *     stale request is cancelled the moment the user collapses
 *     the folder again. The result of an aborted fetch never
 *     reaches the cache.
 *
 * The store is intentionally not exported as a singleton: the
 * Library shell creates one instance per mount via
 * `createTreeLoader(getToken)` and passes it down via prop. That
 * keeps the lifetime tied to the route — leaving `/library` and
 * coming back creates a fresh, abort-clean cache without any
 * teardown gymnastics.
 */

import { createClientApiClient } from "../../api/client";
import type { LibraryNode, LibraryNodePage } from "../../types/library";

/**
 * State for a single folder path inside the cache.
 *
 * - `loading`  the fetch is in flight; the row should render a
 *              spinner placeholder under the parent.
 * - `error`    the fetch failed (network, 5xx, abort handled
 *              separately); shown inline with a retry affordance.
 * - `children` the resolved list of child nodes.
 * - `cursor`   pagination cursor for the next page (null when the
 *              folder has no more rows). The current sprint stops
 *              at the first page; pagination ships in a follow-up.
 */
export interface FolderEntry {
	loading: boolean;
	error: string | null;
	children: LibraryNode[];
	cursor: string | null;
}

export interface TreeLoader {
	/** Reactive map keyed by encoded folder path. */
	readonly folders: Record<string, FolderEntry>;
	/** Reactive set of expanded folder paths. */
	readonly expanded: ReadonlySet<string>;

	/** Toggle a folder's expanded state — fetches children on first open. */
	toggle(path: string): Promise<void>;
	/** Force-expand a folder (used by URL adapter on initial render). */
	expand(path: string): Promise<void>;
	/** Collapse a folder and abort any in-flight fetch for it. */
	collapse(path: string): void;
	/** Retry a failed fetch — clears error then re-issues the request. */
	retry(path: string): Promise<void>;
	/** Aborts every in-flight fetch — call from $effect cleanup. */
	dispose(): void;
}

export function createTreeLoader(
	getToken: () => Promise<string>,
): TreeLoader {
	// Reactive containers — both are $state-backed so consumers can
	// `$derived` over them. We use plain object/Set rather than Map
	// so Svelte 5 deep proxies the structure cleanly.
	const folders = $state<Record<string, FolderEntry>>({});
	const expanded = $state(new Set<string>());

	// AbortController per folder path. Not reactive — the lifecycle
	// is purely network-side, no UI needs to observe it.
	const inflight = new Map<string, AbortController>();

	const api = createClientApiClient(getToken);

	function ensureEntry(path: string): FolderEntry {
		if (!folders[path]) {
			folders[path] = {
				loading: false,
				error: null,
				children: [],
				cursor: null,
			};
		}
		return folders[path]!;
	}

	async function fetchChildren(path: string): Promise<void> {
		const entry = ensureEntry(path);

		// Cancel any previous in-flight fetch for the same folder
		// before issuing the new one. Last-write-wins.
		const previous = inflight.get(path);
		if (previous) previous.abort();

		const controller = new AbortController();
		inflight.set(path, controller);

		entry.loading = true;
		entry.error = null;

		try {
			// The path comes URL-encoded already (segment-by-segment)
			// from the LibraryTreeNode click handler — we forward it
			// verbatim so the router-level `path:path` capture matches
			// the same encoding the backend expects.
			const page = await api.get<LibraryNodePage>(
				`/library/folders/${path}/children`,
				undefined,
				{ signal: controller.signal },
			);

			// If a newer fetch superseded us, drop the result on the
			// floor — the cache is owned by whoever holds the live
			// controller for this path.
			if (inflight.get(path) !== controller) return;

			entry.children = page.items;
			entry.cursor = page.next_cursor;
			entry.loading = false;
		} catch (err: unknown) {
			if (err instanceof DOMException && err.name === "AbortError") {
				// Aborted because the user collapsed the folder or a
				// newer fetch superseded us — leave the entry quiet.
				return;
			}
			if (inflight.get(path) !== controller) return;
			entry.loading = false;
			entry.error =
				err instanceof Error
					? err.message
					: "Failed to load folder.";
		} finally {
			if (inflight.get(path) === controller) {
				inflight.delete(path);
			}
		}
	}

	async function expand(path: string): Promise<void> {
		expanded.add(path);
		const entry = ensureEntry(path);
		// Only fetch if we have not loaded this folder yet (or a
		// previous attempt failed). Re-expanding a successfully
		// loaded folder is free.
		if (entry.children.length === 0 && !entry.loading) {
			await fetchChildren(path);
		}
	}

	function collapse(path: string): void {
		expanded.delete(path);
		const controller = inflight.get(path);
		if (controller) {
			controller.abort();
			inflight.delete(path);
		}
	}

	async function toggle(path: string): Promise<void> {
		if (expanded.has(path)) {
			collapse(path);
		} else {
			await expand(path);
		}
	}

	async function retry(path: string): Promise<void> {
		const entry = folders[path];
		if (!entry) return;
		entry.error = null;
		await fetchChildren(path);
	}

	function dispose(): void {
		for (const controller of inflight.values()) {
			controller.abort();
		}
		inflight.clear();
	}

	return {
		get folders() {
			return folders;
		},
		get expanded() {
			return expanded;
		},
		toggle,
		expand,
		collapse,
		retry,
		dispose,
	};
}
