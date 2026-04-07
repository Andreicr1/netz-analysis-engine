import { describe, expect, it } from "vitest";

import {
	errData,
	isLoaded,
	isStale,
	okData,
	type RouteData,
} from "../route-contract";

describe("route-contract", () => {
	it("okData wraps a value with null error and ISO loadedAt", () => {
		const d = okData({ ticker: "SPY" });
		expect(d.data).toEqual({ ticker: "SPY" });
		expect(d.error).toBeNull();
		expect(() => new Date(d.loadedAt).toISOString()).not.toThrow();
	});

	it("errData wraps an error with null data", () => {
		const d = errData("NOT_FOUND", "fund not found", false);
		expect(d.data).toBeNull();
		expect(d.error).toEqual({
			code: "NOT_FOUND",
			message: "fund not found",
			recoverable: false,
		});
	});

	it("errData defaults recoverable to true", () => {
		const d = errData("TIMEOUT", "upstream slow");
		expect(d.error?.recoverable).toBe(true);
	});

	it("isLoaded narrows to success branch", () => {
		const ok: RouteData<{ id: string }> = okData({ id: "x" });
		expect(isLoaded(ok)).toBe(true);

		const bad: RouteData<{ id: string }> = errData("E", "boom");
		expect(isLoaded(bad)).toBe(false);
	});

	it("isStale detects freshness", () => {
		const fresh = okData({ n: 1 });
		expect(isStale(fresh, 60_000)).toBe(false);

		const stale: RouteData<{ n: number }> = {
			data: { n: 1 },
			error: null,
			loadedAt: new Date(Date.now() - 120_000).toISOString(),
		};
		expect(isStale(stale, 60_000)).toBe(true);
	});

	it("isStale returns true for malformed timestamps", () => {
		const broken: RouteData<unknown> = {
			data: null,
			error: null,
			loadedAt: "not-a-date",
		};
		expect(isStale(broken, 60_000)).toBe(true);
	});
});
