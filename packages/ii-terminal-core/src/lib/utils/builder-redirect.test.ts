/**
 * Unit tests for the /portfolio/builder → /allocation/{profile}
 * redirect resolver (PR-UX-2).
 */
import { describe, expect, test } from "vitest";
import {
	DEFAULT_PROFILE,
	buildBuilderRedirect,
	extractCanonicalPortfolioId,
	normalizeProfile,
} from "./builder-redirect.js";

describe("normalizeProfile", () => {
	test("returns canonical profile when valid", () => {
		expect(normalizeProfile("growth")).toBe("growth");
		expect(normalizeProfile("conservative")).toBe("conservative");
		expect(normalizeProfile("moderate")).toBe("moderate");
	});

	test("is case-insensitive", () => {
		expect(normalizeProfile("Growth")).toBe("growth");
		expect(normalizeProfile("MODERATE")).toBe("moderate");
	});

	test("returns null for unknown / empty / nullish", () => {
		expect(normalizeProfile("aggressive")).toBeNull();
		expect(normalizeProfile("")).toBeNull();
		expect(normalizeProfile(null)).toBeNull();
		expect(normalizeProfile(undefined)).toBeNull();
	});
});

describe("buildBuilderRedirect", () => {
	test("deep-link with growth portfolio resolves to /allocation/growth", () => {
		const params = new URLSearchParams(
			"portfolio_id=11111111-2222-3333-4444-555555555555",
		);
		const dest = buildBuilderRedirect(params, "growth");
		expect(dest.startsWith("/allocation/growth?")).toBe(true);
		expect(dest).toContain("portfolio_id=11111111-2222-3333-4444-555555555555");
		expect(dest).toContain("tab=portfolio");
	});

	test("legacy ?id= is rewritten as portfolio_id and preserved", () => {
		const params = new URLSearchParams(
			"id=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
		);
		const dest = buildBuilderRedirect(params, "conservative");
		expect(dest.startsWith("/allocation/conservative?")).toBe(true);
		expect(dest).toContain("portfolio_id=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
		// Legacy ?id= param must be dropped (rewritten as portfolio_id).
		// Using URLSearchParams to avoid substring matching on
		// ``portfolio_id`` (which contains ``id=``).
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.has("id")).toBe(false);
	});

	test("falls back to DEFAULT_PROFILE when resolved profile is null", () => {
		const params = new URLSearchParams("portfolio_id=anything");
		const dest = buildBuilderRedirect(params, null);
		expect(dest.startsWith(`/allocation/${DEFAULT_PROFILE}?`)).toBe(true);
		expect(DEFAULT_PROFILE).toBe("moderate");
	});

	test("falls back to DEFAULT_PROFILE for invalid resolved profile", () => {
		const params = new URLSearchParams("portfolio_id=anything");
		const dest = buildBuilderRedirect(params, "balanced");
		expect(dest.startsWith(`/allocation/${DEFAULT_PROFILE}?`)).toBe(true);
	});

	test("preserves arbitrary query params untouched", () => {
		const params = new URLSearchParams(
			"portfolio_id=p1&alloc=growth&foo=bar",
		);
		const dest = buildBuilderRedirect(params, "growth");
		expect(dest).toContain("alloc=growth");
		expect(dest).toContain("foo=bar");
		expect(dest).toContain("portfolio_id=p1");
		expect(dest).toContain("tab=portfolio");
	});

	test("forces tab=portfolio even when source omits it", () => {
		const params = new URLSearchParams("");
		const dest = buildBuilderRedirect(params, null);
		expect(dest).toBe(`/allocation/${DEFAULT_PROFILE}?tab=portfolio`);
	});

	test("source ?tab= is honored (last-write-wins on URLSearchParams.set)", () => {
		// If a caller explicitly passes tab=stress, we still rewrite to
		// portfolio because tab=portfolio is set first then the source
		// overwrites — guard test to lock current behavior.
		const params = new URLSearchParams("tab=stress");
		const dest = buildBuilderRedirect(params, null);
		// Source-provided tab wins because it iterates after the seed.
		expect(dest).toContain("tab=stress");
	});

	// ── Regression: lookup ↔ emit must agree on canonical id ──────
	// Codex P2: previously the loader read get("portfolio_id") ?? get("id")
	// while the builder iterated source params with set() last-write-wins,
	// so URLs combining both keys (or repeating one) could land on the
	// /allocation/{profile} route for the wrong portfolio.

	test("URL with both portfolio_id then id keeps portfolio_id as canonical (id-after-portfolio_id ordering)", () => {
		const params = new URLSearchParams("portfolio_id=BBBB&id=AAAA");
		const dest = buildBuilderRedirect(params, "growth");
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.getAll("portfolio_id")).toEqual(["BBBB"]);
		expect(query.has("id")).toBe(false);
	});

	test("URL with id then portfolio_id keeps portfolio_id as canonical (portfolio_id-after-id ordering)", () => {
		const params = new URLSearchParams("id=AAAA&portfolio_id=BBBB");
		const dest = buildBuilderRedirect(params, "growth");
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.getAll("portfolio_id")).toEqual(["BBBB"]);
		expect(query.has("id")).toBe(false);
	});

	test("repeated portfolio_id collapses to the first value (matches URLSearchParams.get precedence)", () => {
		const params = new URLSearchParams(
			"portfolio_id=AAAA&portfolio_id=BBBB",
		);
		const dest = buildBuilderRedirect(params, "growth");
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.getAll("portfolio_id")).toEqual(["AAAA"]);
	});

	test("repeated legacy id collapses to the first value", () => {
		const params = new URLSearchParams("id=AAAA&id=BBBB");
		const dest = buildBuilderRedirect(params, "growth");
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.getAll("portfolio_id")).toEqual(["AAAA"]);
		expect(query.has("id")).toBe(false);
	});

	test("no id keys present omits portfolio_id from destination", () => {
		const params = new URLSearchParams("foo=bar");
		const dest = buildBuilderRedirect(params, null);
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.has("portfolio_id")).toBe(false);
		expect(query.has("id")).toBe(false);
		expect(query.get("foo")).toBe("bar");
	});
});

describe("extractCanonicalPortfolioId", () => {
	test("prefers portfolio_id over id", () => {
		const params = new URLSearchParams("id=AAAA&portfolio_id=BBBB");
		expect(extractCanonicalPortfolioId(params)).toBe("BBBB");
	});

	test("falls back to legacy id when portfolio_id absent", () => {
		const params = new URLSearchParams("id=AAAA");
		expect(extractCanonicalPortfolioId(params)).toBe("AAAA");
	});

	test("returns first value when key is repeated", () => {
		const params = new URLSearchParams("portfolio_id=AAAA&portfolio_id=BBBB");
		expect(extractCanonicalPortfolioId(params)).toBe("AAAA");
	});

	test("returns null when neither key is present", () => {
		const params = new URLSearchParams("foo=bar");
		expect(extractCanonicalPortfolioId(params)).toBeNull();
	});
});
