/*
 * tests/choreo.test.ts
 * ====================
 *
 * Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md §1.1
 *
 * Pure-function tests for the terminal motion grammar. Choreo is
 * the SHARED timing system that every Svelte transition and every
 * ECharts `animationDelay` callback consumes — a regression here
 * desynchronises the entire `(terminal)/` motion choreography, so
 * we lock the contract numerically.
 *
 * Coverage targets:
 *   - Slot delays match the canonical schedule (chrome → ambient).
 *   - `delayFor` collapses every slot to 0ms under reduced motion.
 *   - `durationFor` collapses every named duration to 0ms under
 *     reduced motion (matches the CSS `@media (prefers-reduced-
 *     motion)` block in tokens/terminal.css).
 *   - `animationDelayForSlot` returns a callback ECharts can use,
 *     with optional per-item stagger arithmetic.
 *   - `prefersReducedMotion` is SSR-safe (no `window` → false).
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import {
	choreo,
	terminalDuration,
	terminalEasing,
	terminalBezier,
	delayFor,
	durationFor,
	animationDelayForSlot,
	prefersReducedMotion,
	type ChoreoSlot,
} from "../src/lib/charts/choreo.js";

describe("choreo — slot delays", () => {
	it("exposes the five canonical slots in monotonically increasing order", () => {
		expect(choreo.chrome).toBe(0);
		expect(choreo.primary).toBe(120);
		expect(choreo.secondary).toBe(220);
		expect(choreo.tail).toBe(320);
		expect(choreo.ambient).toBe(420);

		const ordered = [choreo.chrome, choreo.primary, choreo.secondary, choreo.tail, choreo.ambient];
		const sorted = [...ordered].sort((a, b) => a - b);
		expect(ordered).toEqual(sorted);
	});

	it("freezes the slot dictionary so accidental writes throw", () => {
		expect(Object.isFrozen(choreo)).toBe(true);
	});
});

describe("choreo — terminalDuration", () => {
	it("locks the three canonical durations", () => {
		expect(terminalDuration.opening).toBe(900);
		expect(terminalDuration.update).toBe(320);
		expect(terminalDuration.tick).toBe(160);
	});

	it("freezes the duration dictionary", () => {
		expect(Object.isFrozen(terminalDuration)).toBe(true);
	});
});

describe("choreo — easing tables", () => {
	it("exposes the named ECharts easings", () => {
		expect(terminalEasing.cubicOut).toBe("cubicOut");
		expect(terminalEasing.quintOut).toBe("quintOut");
	});

	it("exposes the cubic-bezier tuples that mirror the CSS tokens", () => {
		expect(terminalBezier.cubicOut).toEqual([0.33, 1, 0.68, 1]);
		expect(terminalBezier.quintOut).toEqual([0.23, 1, 0.32, 1]);
	});
});

describe("delayFor", () => {
	const slots: ChoreoSlot[] = ["chrome", "primary", "secondary", "tail", "ambient"];

	it("returns the slot delay verbatim when reduced motion is OFF", () => {
		for (const slot of slots) {
			expect(delayFor(slot)).toBe(choreo[slot]);
			expect(delayFor(slot, false)).toBe(choreo[slot]);
		}
	});

	it("collapses every slot to 0ms when reduced motion is ON", () => {
		for (const slot of slots) {
			expect(delayFor(slot, true)).toBe(0);
		}
	});

	it("returns 220ms specifically for the secondary slot (lock against rename)", () => {
		expect(delayFor("secondary")).toBe(220);
	});
});

describe("durationFor", () => {
	it("returns the duration verbatim when reduced motion is OFF", () => {
		expect(durationFor("opening")).toBe(900);
		expect(durationFor("update")).toBe(320);
		expect(durationFor("tick")).toBe(160);
	});

	it("collapses every duration to 0ms when reduced motion is ON", () => {
		expect(durationFor("opening", true)).toBe(0);
		expect(durationFor("update", true)).toBe(0);
		expect(durationFor("tick", true)).toBe(0);
	});
});

describe("animationDelayForSlot", () => {
	it("without perItem returns a constant function bound to the slot delay", () => {
		const fn = animationDelayForSlot("primary");
		expect(typeof fn).toBe("function");
		expect(fn(0)).toBe(120);
		expect(fn(5)).toBe(120);
		expect(fn(99)).toBe(120);
	});

	it("with perItem layers the per-index stagger on top of the slot base", () => {
		const fn = animationDelayForSlot("secondary", (idx) => idx * 20);
		expect(fn(0)).toBe(220);
		expect(fn(1)).toBe(240);
		expect(fn(4)).toBe(300);
	});

	it("works for the chrome slot (base = 0) — perItem fully drives the value", () => {
		const fn = animationDelayForSlot("chrome", (idx) => idx * 10);
		expect(fn(0)).toBe(0);
		expect(fn(7)).toBe(70);
	});
});

describe("prefersReducedMotion", () => {
	const originalMatchMedia = (
		globalThis as { matchMedia?: (query: string) => MediaQueryList }
	).matchMedia;

	afterEach(() => {
		if (originalMatchMedia === undefined) {
			delete (globalThis as { matchMedia?: unknown }).matchMedia;
		} else {
			(globalThis as { matchMedia?: typeof originalMatchMedia }).matchMedia = originalMatchMedia;
		}
	});

	it("returns false when window.matchMedia is unavailable (SSR fallback)", () => {
		delete (globalThis as { matchMedia?: unknown }).matchMedia;
		expect(prefersReducedMotion()).toBe(false);
	});

	it("returns true when the media query reports a match", () => {
		(globalThis as { matchMedia?: (q: string) => MediaQueryList }).matchMedia = vi.fn(
			(query: string) =>
				({
					matches: query.includes("reduce"),
					media: query,
					onchange: null,
					addListener: () => {},
					removeListener: () => {},
					addEventListener: () => {},
					removeEventListener: () => {},
					dispatchEvent: () => false,
				}) as unknown as MediaQueryList,
		);
		expect(prefersReducedMotion()).toBe(true);
	});

	it("returns false when the media query reports no match", () => {
		(globalThis as { matchMedia?: (q: string) => MediaQueryList }).matchMedia = vi.fn(
			(query: string) =>
				({
					matches: false,
					media: query,
					onchange: null,
					addListener: () => {},
					removeListener: () => {},
					addEventListener: () => {},
					removeEventListener: () => {},
					dispatchEvent: () => false,
				}) as unknown as MediaQueryList,
		);
		expect(prefersReducedMotion()).toBe(false);
	});
});
