/**
 * Route data contract — typed load return shape for detail pages.
 *
 * Stability Guardrails §3.2 — satisfies P3 (Isolated), P4 (Lifecycle),
 * P6 (Fault-Tolerant).
 *
 * Problem this solves
 * -------------------
 * SvelteKit's default error handling for `load` functions is to call
 * `throw error(status, message)`, which bubbles to the framework's
 * `+error.svelte` boundary. That boundary is minimalist by default
 * (the black-screen failure mode documented in §7.2 of the design
 * spec): a 404 on a fund detail page becomes a blank canvas with no
 * retry affordance and no actionable message.
 *
 * The Route Data Contract replaces that pattern with an explicit
 * result type: every detail page's `+page.server.ts` (or `+page.ts`)
 * returns a `RouteData<T>` value that the page component then
 * renders across three explicit branches:
 *
 *   {#if routeData.error} <PanelErrorState … />
 *   {:else if !routeData.data} <PanelEmptyState … />
 *   {:else} <svelte:boundary><DetailPanel data={routeData.data} /></svelte:boundary>
 *
 * No `throw error()`. No SvelteKit error boundary. No tab-wide
 * failure. The component always renders something the user can act
 * on.
 *
 * Enforcement
 * -----------
 * The `require-load-timeout` and `no-throw-error-in-load` ESLint
 * rules (added in commit 11 / commit 12) enforce:
 *   1. Every `load` function wraps its fetch in
 *      `AbortSignal.timeout(...)`.
 *   2. Every `load` function returns `RouteData<T>` instead of
 *      throwing.
 */

export interface RouteError {
	/** Stable machine-readable code (e.g. "NOT_FOUND", "TIMEOUT"). */
	code: string;
	/** Human-readable message — safe for direct display. */
	message: string;
	/** Whether the user should see a "try again" affordance. */
	recoverable: boolean;
}

export interface RouteData<T> {
	data: T | null;
	error: RouteError | null;
	/** ISO-8601 timestamp of when this load completed. */
	loadedAt: string;
}

/** Build a successful RouteData payload. */
export function okData<T>(data: T): RouteData<T> {
	return {
		data,
		error: null,
		loadedAt: new Date().toISOString(),
	};
}

/** Build a failure RouteData payload. */
export function errData(
	code: string,
	message: string,
	recoverable: boolean = true,
): RouteData<never> {
	return {
		data: null,
		error: { code, message, recoverable },
		loadedAt: new Date().toISOString(),
	};
}

/**
 * Check whether a RouteData is older than `maxAgeMs` milliseconds.
 * Callers use this to decide whether to kick off a refresh.
 */
export function isStale(
	routeData: RouteData<unknown>,
	maxAgeMs: number,
): boolean {
	const loaded = Date.parse(routeData.loadedAt);
	if (Number.isNaN(loaded)) return true;
	return Date.now() - loaded > maxAgeMs;
}

/**
 * Type guard: narrow RouteData<T> to its success branch.
 * Usage:
 *   if (isLoaded(routeData)) {
 *     routeData.data.field // typed as T
 *   }
 */
export function isLoaded<T>(
	routeData: RouteData<T>,
): routeData is RouteData<T> & { data: T; error: null } {
	return routeData.data !== null && routeData.error === null;
}
