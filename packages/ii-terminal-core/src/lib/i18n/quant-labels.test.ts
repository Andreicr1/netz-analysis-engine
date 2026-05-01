/**
 * PR-BE-7 — profileDisplayLabel canonical helper.
 *
 * Verifies the slug → product copy mapping, the legacy ``aggressive``
 * alias rewrite, and the unknown-slug fallback.
 */
import { describe, expect, test } from "vitest";
import { profileDisplayLabel } from "./quant-labels";

describe("profileDisplayLabel", () => {
	test("growth dense → Dynamic", () => {
		expect(profileDisplayLabel("growth", "dense")).toBe("Dynamic");
	});

	test("growth full → Dynamic Growth", () => {
		expect(profileDisplayLabel("growth", "full")).toBe("Dynamic Growth");
	});

	test("growth defaults to full when context omitted", () => {
		expect(profileDisplayLabel("growth")).toBe("Dynamic Growth");
	});

	test("aggressive dense alias → Dynamic", () => {
		expect(profileDisplayLabel("aggressive", "dense")).toBe("Dynamic");
	});

	test("aggressive full alias → Dynamic Growth", () => {
		expect(profileDisplayLabel("aggressive", "full")).toBe("Dynamic Growth");
	});

	test("conservative dense + full identical", () => {
		expect(profileDisplayLabel("conservative", "dense")).toBe("Conservative");
		expect(profileDisplayLabel("conservative", "full")).toBe("Conservative");
	});

	test("moderate dense + full identical (display label is 'Balanced')", () => {
		expect(profileDisplayLabel("moderate", "dense")).toBe("Balanced");
		expect(profileDisplayLabel("moderate", "full")).toBe("Balanced");
	});

	test("unknown profile falls through to title-case", () => {
		// Forward-compat fallback for tenant-scoped custom profiles
		// (Q6 v2 / post-GA — custom profiles via ConfigService).
		expect(profileDisplayLabel("speculative", "full")).toBe("Speculative");
	});

	test("uppercase canonical slug normalises to canonical label", () => {
		expect(profileDisplayLabel("GROWTH", "dense")).toBe("Dynamic");
	});
});
