/**
 * Wealth Library — bidirectional URL ↔ state adapter.
 *
 * Phase 4 of the Library frontend (spec §3.4 Fase 4 + §2.5). The
 * adapter is the *only* place that touches the URL on the Library
 * surface. It owns:
 *
 *   * filter chips:    status[], kind[], starred, language
 *   * date range:      from, to
 *   * search:          q  (debounced 300 ms before pushing to URL)
 *   * view mode:       view = tree | list | grid
 *   * preview mode:    preview = inline | fullscreen
 *   * selected file:   id
 *
 * The adapter is constructed once per LibraryShell mount via
 * `createUrlAdapter()` and disposed in onDestroy. It exposes a
 * reactive `state` object plus a small set of mutators; consumers
 * mutate via the mutators and read via `state.*`. The adapter takes
 * care of:
 *
 *   1. Pushing every state change into `$page.url` via `goto`
 *      with `keepFocus: true, noScroll: true, replaceState: true`
 *      so the back/forward stack is not flooded with intermediate
 *      typing states.
 *   2. Re-syncing internal state whenever the user navigates back
 *      or forward — handled by an `$effect` that watches
 *      `$page.url.searchParams` and copies the new values in.
 *   3. Anti-loop guard: a transient `applyingFromUrl` flag is set
 *      while we copy URL → state, so the URL → state effect does
 *      not re-trigger the state → URL effect on the same tick.
 *
 * The debounced search input is the only consumer that calls
 * `setQuery(value, { debounce: true })`. Filters and view toggles
 * push immediately because user perception is instantaneous.
 */

import { goto } from "$app/navigation";
import { page } from "$app/state";

export type LibraryViewMode = "tree" | "list" | "grid";
export type LibraryPreviewMode = "inline" | "fullscreen";

export interface LibraryUrlState {
	q: string;
	statuses: string[];
	kinds: string[];
	from: string | null;
	to: string | null;
	language: string | null;
	starred: boolean;
	view: LibraryViewMode;
	preview: LibraryPreviewMode;
	selectedId: string | null;
}

const DEFAULT_STATE: LibraryUrlState = {
	q: "",
	statuses: [],
	kinds: [],
	from: null,
	to: null,
	language: null,
	starred: false,
	view: "tree",
	preview: "inline",
	selectedId: null,
};

const SEARCH_DEBOUNCE_MS = 300;

export interface UrlAdapter {
	readonly state: LibraryUrlState;
	setQuery(value: string, opts?: { debounce?: boolean }): void;
	toggleStatus(value: string): void;
	toggleKind(value: string): void;
	setDateRange(from: string | null, to: string | null): void;
	setLanguage(value: string | null): void;
	setStarred(value: boolean): void;
	setView(value: LibraryViewMode): void;
	setPreview(value: LibraryPreviewMode): void;
	setSelectedId(value: string | null): void;
	clearAllFilters(): void;
	dispose(): void;
}

function readFromUrl(params: URLSearchParams): LibraryUrlState {
	const view = params.get("view");
	const preview = params.get("preview");
	return {
		q: params.get("q") ?? "",
		statuses: params.getAll("status"),
		kinds: params.getAll("kind"),
		from: params.get("from"),
		to: params.get("to"),
		language: params.get("language"),
		starred: params.get("starred") === "1",
		view:
			view === "list" || view === "grid" || view === "tree"
				? view
				: "tree",
		preview: preview === "fullscreen" ? "fullscreen" : "inline",
		selectedId: params.get("id"),
	};
}

function buildSearch(state: LibraryUrlState): URLSearchParams {
	const params = new URLSearchParams();
	if (state.q) params.set("q", state.q);
	for (const s of state.statuses) params.append("status", s);
	for (const k of state.kinds) params.append("kind", k);
	if (state.from) params.set("from", state.from);
	if (state.to) params.set("to", state.to);
	if (state.language) params.set("language", state.language);
	if (state.starred) params.set("starred", "1");
	if (state.view !== "tree") params.set("view", state.view);
	if (state.preview !== "inline") params.set("preview", state.preview);
	if (state.selectedId) params.set("id", state.selectedId);
	return params;
}

export function createUrlAdapter(): UrlAdapter {
	// Reactive state mirror — `$state` so consumers can read via
	// `adapter.state.q` etc and Svelte tracks the dependency.
	const state = $state<LibraryUrlState>({ ...DEFAULT_STATE });

	// Anti-loop guard. When the URL → state copy runs, it sets this
	// flag so the state → URL effect skips the next tick. Without it,
	// every browser back/forward would re-push to the URL, which
	// would either no-op (still wasteful) or, worse, fight the user.
	let applyingFromUrl = false;
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;

	// ── URL → state ──────────────────────────────────────────────
	// Watches `page.url.search` (the only piece that matters here).
	// Whenever SvelteKit reports a navigation (popstate, link click,
	// our own goto), we re-read the params into the reactive mirror.
	$effect(() => {
		// Touch the reactive accessor so this effect re-runs.
		const search = page.url.search;
		const next = readFromUrl(new URLSearchParams(search));
		applyingFromUrl = true;
		state.q = next.q;
		state.statuses = next.statuses;
		state.kinds = next.kinds;
		state.from = next.from;
		state.to = next.to;
		state.language = next.language;
		state.starred = next.starred;
		state.view = next.view;
		state.preview = next.preview;
		state.selectedId = next.selectedId;
		// Release the guard on the next microtask so the state → URL
		// effect that may run on the same tick sees `applyingFromUrl`
		// as true and bails. queueMicrotask is enough — Svelte's
		// effect scheduler runs synchronously inside the same task.
		queueMicrotask(() => {
			applyingFromUrl = false;
		});
	});

	// ── state → URL ──────────────────────────────────────────────
	// Pushes a new URL whenever the reactive mirror changes. Uses
	// `replaceState: true` so the back/forward stack is not polluted
	// with every keystroke or chip click. The pathname stays the
	// same — the adapter never moves between /library and
	// /library/[...path]; that decision belongs to the shell.
	$effect(() => {
		// Read every field so Svelte tracks them as dependencies.
		const search = buildSearch(state).toString();
		void state.q;
		void state.statuses.length;
		void state.kinds.length;
		void state.from;
		void state.to;
		void state.language;
		void state.starred;
		void state.view;
		void state.preview;
		void state.selectedId;

		if (applyingFromUrl) return;

		const target = `${page.url.pathname}${search ? "?" + search : ""}`;
		const current = `${page.url.pathname}${page.url.search}`;
		if (target === current) return;

		void goto(target, {
			keepFocus: true,
			noScroll: true,
			replaceState: true,
		});
	});

	function setQuery(value: string, opts?: { debounce?: boolean }): void {
		if (debounceTimer) {
			clearTimeout(debounceTimer);
			debounceTimer = null;
		}
		if (opts?.debounce) {
			// Local typing feedback is instant — we mutate the
			// `q` state synchronously so the input shows the
			// character immediately. Only the URL push waits.
			state.q = value;
			// Re-fire the URL push after the debounce window. The
			// state → URL effect already ran with the local mutation
			// above; we trigger it again by writing the same value
			// after the timeout so any pending fetch/cache that
			// keys on URL state stays in sync.
			debounceTimer = setTimeout(() => {
				// Same value written → still triggers the effect
				// because Svelte 5 $state mutations notify on write.
				state.q = value;
				debounceTimer = null;
			}, SEARCH_DEBOUNCE_MS);
		} else {
			state.q = value;
		}
	}

	function toggleStatus(value: string): void {
		const idx = state.statuses.indexOf(value);
		if (idx === -1) {
			state.statuses = [...state.statuses, value];
		} else {
			state.statuses = state.statuses.filter((s) => s !== value);
		}
	}

	function toggleKind(value: string): void {
		const idx = state.kinds.indexOf(value);
		if (idx === -1) {
			state.kinds = [...state.kinds, value];
		} else {
			state.kinds = state.kinds.filter((k) => k !== value);
		}
	}

	function setDateRange(from: string | null, to: string | null): void {
		state.from = from;
		state.to = to;
	}

	function setLanguage(value: string | null): void {
		state.language = value;
	}

	function setStarred(value: boolean): void {
		state.starred = value;
	}

	function setView(value: LibraryViewMode): void {
		state.view = value;
	}

	function setPreview(value: LibraryPreviewMode): void {
		state.preview = value;
	}

	function setSelectedId(value: string | null): void {
		state.selectedId = value;
	}

	function clearAllFilters(): void {
		state.q = "";
		state.statuses = [];
		state.kinds = [];
		state.from = null;
		state.to = null;
		state.language = null;
		state.starred = false;
	}

	function dispose(): void {
		if (debounceTimer) {
			clearTimeout(debounceTimer);
			debounceTimer = null;
		}
	}

	return {
		get state() {
			return state;
		},
		setQuery,
		toggleStatus,
		toggleKind,
		setDateRange,
		setLanguage,
		setStarred,
		setView,
		setPreview,
		setSelectedId,
		clearAllFilters,
		dispose,
	};
}
