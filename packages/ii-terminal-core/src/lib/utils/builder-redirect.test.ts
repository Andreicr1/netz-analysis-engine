/**
 * Unit tests for the /portfolio/builder → /allocation/{profile}
 * redirect resolver (PR-UX-2).
 */
import { describe, expect, test } from "vitest";
import {
	DEFAULT_PROFILE,
	buildBuilderRedirect,
	extractCanonicalPortfolioId,
	isValidPortfolioId,
	normalizeProfile,
} from "./builder-redirect.js";

const UUID_A = "11111111-2222-3333-4444-555555555555";
const UUID_B = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

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
			`portfolio_id=${UUID_A}&alloc=growth&foo=bar`,
		);
		const dest = buildBuilderRedirect(params, "growth");
		expect(dest).toContain("alloc=growth");
		expect(dest).toContain("foo=bar");
		expect(dest).toContain(`portfolio_id=${UUID_A}`);
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
		const params = new URLSearchParams(`portfolio_id=${UUID_B}&id=${UUID_A}`);
		const dest = buildBuilderRedirect(params, "growth");
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.getAll("portfolio_id")).toEqual([UUID_B]);
		expect(query.has("id")).toBe(false);
	});

	test("URL with id then portfolio_id keeps portfolio_id as canonical (portfolio_id-after-id ordering)", () => {
		const params = new URLSearchParams(`id=${UUID_A}&portfolio_id=${UUID_B}`);
		const dest = buildBuilderRedirect(params, "growth");
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.getAll("portfolio_id")).toEqual([UUID_B]);
		expect(query.has("id")).toBe(false);
	});

	test("repeated portfolio_id collapses to the first value (matches URLSearchParams.get precedence)", () => {
		const params = new URLSearchParams(
			`portfolio_id=${UUID_A}&portfolio_id=${UUID_B}`,
		);
		const dest = buildBuilderRedirect(params, "growth");
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.getAll("portfolio_id")).toEqual([UUID_A]);
	});

	test("repeated legacy id collapses to the first value", () => {
		const params = new URLSearchParams(`id=${UUID_A}&id=${UUID_B}`);
		const dest = buildBuilderRedirect(params, "growth");
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.getAll("portfolio_id")).toEqual([UUID_A]);
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

	// ── Security: non-UUID ids must NOT reach the redirect ────────
	// Codex P2: a crafted ?portfolio_id=../foo could otherwise land
	// in /allocation/{profile}?portfolio_id=../foo and propagate to
	// any consumer that interpolates it into a path. UUID validation
	// is the single source of truth in extractCanonicalPortfolioId.

	test("non-UUID portfolio_id is silently dropped from destination", () => {
		const params = new URLSearchParams("portfolio_id=../../etc/passwd");
		const dest = buildBuilderRedirect(params, null);
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.has("portfolio_id")).toBe(false);
		expect(query.has("id")).toBe(false);
	});

	test("non-UUID legacy id is silently dropped from destination", () => {
		const params = new URLSearchParams("id=foo/bar");
		const dest = buildBuilderRedirect(params, null);
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.has("portfolio_id")).toBe(false);
		expect(query.has("id")).toBe(false);
	});

	test("URL-encoded path-traversal payload is rejected as non-UUID", () => {
		const params = new URLSearchParams("portfolio_id=%2e%2e%2ffoo");
		const dest = buildBuilderRedirect(params, null);
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.has("portfolio_id")).toBe(false);
	});

	test("when portfolio_id is non-UUID but id is a valid UUID, id wins via fallback", () => {
		// Documents the precedence: non-UUID portfolio_id is treated as
		// missing for canonicalization, so the legacy id (if a valid
		// UUID) is used as the fallback. Mirrors extractCanonicalPortfolioId.
		const params = new URLSearchParams(`portfolio_id=garbage&id=${UUID_A}`);
		const dest = buildBuilderRedirect(params, "growth");
		const query = new URLSearchParams(dest.split("?")[1] ?? "");
		expect(query.getAll("portfolio_id")).toEqual([UUID_A]);
		expect(query.has("id")).toBe(false);
	});
});

describe("isValidPortfolioId", () => {
	test("accepts canonical lowercase v4 UUIDs", () => {
		expect(isValidPortfolioId(UUID_A)).toBe(true);
		expect(isValidPortfolioId(UUID_B)).toBe(true);
	});

	test("accepts mixed-case UUIDs (RFC 4122 is case-insensitive)", () => {
		expect(
			isValidPortfolioId("11111111-2222-3333-4444-AaBbCcDdEeFf"),
		).toBe(true);
	});

	test("rejects non-UUID strings", () => {
		expect(isValidPortfolioId("garbage")).toBe(false);
		expect(isValidPortfolioId("p1")).toBe(false);
		expect(isValidPortfolioId("anything")).toBe(false);
		expect(isValidPortfolioId("")).toBe(false);
	});

	test("rejects path-traversal payloads", () => {
		expect(isValidPortfolioId("..")).toBe(false);
		expect(isValidPortfolioId("../../etc/passwd")).toBe(false);
		expect(isValidPortfolioId("foo/bar")).toBe(false);
		expect(isValidPortfolioId("%2e%2e%2ffoo")).toBe(false);
	});

	test("rejects UUID with extra path segment appended", () => {
		expect(isValidPortfolioId(`${UUID_A}/extra`)).toBe(false);
		expect(isValidPortfolioId(`${UUID_A}?injected=1`)).toBe(false);
	});

	test("rejects null / undefined", () => {
		expect(isValidPortfolioId(null)).toBe(false);
		expect(isValidPortfolioId(undefined)).toBe(false);
	});
});

describe("extractCanonicalPortfolioId", () => {
	test("prefers portfolio_id over id when both are valid UUIDs", () => {
		const params = new URLSearchParams(`id=${UUID_A}&portfolio_id=${UUID_B}`);
		expect(extractCanonicalPortfolioId(params)).toBe(UUID_B);
	});

	test("falls back to legacy id when portfolio_id absent", () => {
		const params = new URLSearchParams(`id=${UUID_A}`);
		expect(extractCanonicalPortfolioId(params)).toBe(UUID_A);
	});

	test("returns first value when key is repeated", () => {
		const params = new URLSearchParams(
			`portfolio_id=${UUID_A}&portfolio_id=${UUID_B}`,
		);
		expect(extractCanonicalPortfolioId(params)).toBe(UUID_A);
	});

	test("returns null when neither key is present", () => {
		const params = new URLSearchParams("foo=bar");
		expect(extractCanonicalPortfolioId(params)).toBeNull();
	});

	test("returns null for non-UUID portfolio_id with no fallback id", () => {
		const params = new URLSearchParams("portfolio_id=garbage");
		expect(extractCanonicalPortfolioId(params)).toBeNull();
	});

	test("returns null for non-UUID legacy id", () => {
		const params = new URLSearchParams("id=garbage");
		expect(extractCanonicalPortfolioId(params)).toBeNull();
	});

	test("falls through invalid portfolio_id to a valid legacy id", () => {
		// Conservative-but-permissive precedence: a malformed canonical
		// key shouldn't shadow a usable legacy fallback. Both must be
		// invalid for the helper to give up.
		const params = new URLSearchParams(`portfolio_id=garbage&id=${UUID_A}`);
		expect(extractCanonicalPortfolioId(params)).toBe(UUID_A);
	});

	test("rejects path-traversal portfolio_id even when no fallback id present", () => {
		const params = new URLSearchParams("portfolio_id=../../etc/passwd");
		expect(extractCanonicalPortfolioId(params)).toBeNull();
	});
});
