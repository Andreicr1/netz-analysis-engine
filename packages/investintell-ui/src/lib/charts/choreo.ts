/**
 * Netz Wealth OS — Terminal Motion Grammar (choreo)
 * =================================================
 *
 * Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md §1.1
 *
 * ONE shared timing system, consumed by EVERY Svelte transition
 * and EVERY ECharts animationDelay across `(terminal)/**`. The
 * Phase 4.2 War Room cascade becomes a consumer, not a special
 * case. Lint rule (see frontends/eslint.config.js) forbids inline
 * `animationDuration` / `animationDelay` literals outside of this
 * module — every Svelte component and chart factory MUST import
 * `choreo`, `terminalEasing`, or `terminalDuration`.
 *
 * The five named slots fire in sequence on surface open:
 *
 *   chrome     0ms   shell frame, topbar, panel chrome
 *   primary    120ms hero chart / reactor panel
 *   secondary  220ms supporting panels
 *   tail       320ms tertiary strips, sparklines
 *   ambient    420ms legends, footers, peripheral metadata
 *
 * Durations:
 *   opening  900ms — first paint of a surface, hero-scale reveal
 *   update   320ms — subsequent data updates, no re-layout
 *   tick     160ms — ticker flash, live-dot pulse, cell highlight
 *
 * Easings:
 *   cubicOut   for ECharts `animationEasing`
 *   quintOut   for Svelte `fly` / `fade` / `scale` transitions
 *
 * These are mirrored as CSS custom properties in
 * `tokens/terminal.css` (--terminal-motion-*). Svelte transitions
 * and inline styles should prefer the CSS variables; TypeScript
 * code passed to ECharts uses the numeric exports below.
 */

/** Named delay slots — monotonically increasing, grouped by role. */
export const choreo = Object.freeze({
	/** Shell chrome, topbar reveal, panel borders. Fires first. */
	chrome: 0,
	/** Hero chart / reactor panel — the visual centerpiece. */
	primary: 120,
	/** Supporting panels (secondary KPIs, peer groups). */
	secondary: 220,
	/** Tertiary strips, sparklines, inline badges. */
	tail: 320,
	/** Legends, footers, ambient metadata. Fires last. */
	ambient: 420,
}) satisfies Readonly<Record<ChoreoSlot, number>>;

export type ChoreoSlot = "chrome" | "primary" | "secondary" | "tail" | "ambient";

/** Canonical terminal animation durations. */
export const terminalDuration = Object.freeze({
	/** Opening reveal of a surface (hero-scale). */
	opening: 900,
	/** Data update — no re-layout, rebind series/extent. */
	update: 320,
	/** Ticker flash, live-dot pulse, cell highlight. */
	tick: 160,
}) satisfies Readonly<Record<TerminalDurationName, number>>;

export type TerminalDurationName = "opening" | "update" | "tick";

/**
 * Easing curves.
 *
 * ECharts accepts named strings (`cubicOut`) or a JS function.
 * We expose both a named string (for ECharts option objects) and
 * the literal cubic-bezier tuple (for Svelte transitions /
 * Web Animations API callers that want the curve in-line).
 */
export const terminalEasing = Object.freeze({
	/** For ECharts `animationEasing` / `animationEasingUpdate`. */
	cubicOut: "cubicOut" as const,
	/** For Svelte transitions (fly, fade, scale). Derived from tokens. */
	quintOut: "quintOut" as const,
});

/** Raw cubic-bezier tuples matching the CSS token definitions. */
export const terminalBezier = Object.freeze({
	/** cubic-bezier(0.33, 1, 0.68, 1) — matches --terminal-motion-easing-out */
	cubicOut: [0.33, 1, 0.68, 1] as const,
	/** cubic-bezier(0.23, 1, 0.32, 1) — matches --terminal-motion-easing-quint */
	quintOut: [0.23, 1, 0.32, 1] as const,
});

/**
 * Build an ECharts `animationDelay` function bound to a slot.
 *
 * Used inside `createTerminalChartOptions` to stagger series
 * reveals while still respecting the shared slot schedule. The
 * returned callback is what ECharts expects: `(idx) => number`.
 *
 * Example:
 *   animationDelay: animationDelayForSlot('primary')
 *   animationDelay: animationDelayForSlot('primary', (idx) => idx * 20)
 */
export function animationDelayForSlot(
	slot: ChoreoSlot,
	perItem?: (idx: number) => number,
): (idx: number) => number {
	const base = choreo[slot];
	if (perItem === undefined) {
		return () => base;
	}
	return (idx: number) => base + perItem(idx);
}

/** Delay slot lookup that returns `0` when reduced motion is on. */
export function delayFor(slot: ChoreoSlot, reducedMotion: boolean = false): number {
	return reducedMotion ? 0 : choreo[slot];
}

/** Duration lookup that honors reduced motion. */
export function durationFor(name: TerminalDurationName, reducedMotion: boolean = false): number {
	return reducedMotion ? 0 : terminalDuration[name];
}

/**
 * Read the user's current reduced-motion preference. Safe to
 * call on the server — returns `false` when `window` is absent.
 */
export function prefersReducedMotion(): boolean {
	if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
		return false;
	}
	return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
