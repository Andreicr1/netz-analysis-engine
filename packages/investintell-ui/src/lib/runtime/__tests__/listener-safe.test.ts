import { describe, expect, it, vi } from "vitest";

import { createMountedGuard } from "../listener-safe.svelte";

describe("createMountedGuard", () => {
	it("returns undefined when not started", () => {
		const g = createMountedGuard();
		const fn = vi.fn(() => 42);
		expect(g.guard(fn)).toBeUndefined();
		expect(fn).not.toHaveBeenCalled();
	});

	it("runs fn when started", () => {
		const g = createMountedGuard();
		g.start();
		expect(g.mounted).toBe(true);
		expect(g.guard(() => 42)).toBe(42);
	});

	it("skips fn after stop", () => {
		const g = createMountedGuard();
		g.start();
		g.stop();
		expect(g.mounted).toBe(false);
		const fn = vi.fn();
		expect(g.guard(fn)).toBeUndefined();
		expect(fn).not.toHaveBeenCalled();
	});

	it("can be restarted", () => {
		const g = createMountedGuard();
		g.start();
		g.stop();
		g.start();
		expect(g.guard(() => "ok")).toBe("ok");
	});
});
