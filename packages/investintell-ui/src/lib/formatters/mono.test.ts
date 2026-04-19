import { describe, expect, test } from "vitest";
import {
	formatCompactCurrency,
	formatMonoPercent,
	formatMonoTime,
	formatPpDrift,
} from "./mono.js";

const EM_DASH = "\u2014";
const MINUS = "\u2212";

describe("formatMonoTime", () => {
	test("UTC with zero-padded HH:MM:SS", () => {
		const d = new Date(Date.UTC(2026, 3, 18, 9, 5, 7));
		expect(formatMonoTime(d, "utc")).toBe("09:05:07 UTC");
	});

	test("UTC handles end-of-day", () => {
		const d = new Date(Date.UTC(2026, 3, 18, 23, 59, 59));
		expect(formatMonoTime(d)).toBe("23:59:59 UTC");
	});

	test("local mode has no UTC suffix", () => {
		const d = new Date(2026, 3, 18, 8, 3, 4);
		expect(formatMonoTime(d, "local")).toBe("08:03:04");
	});
});

describe("formatCompactCurrency", () => {
	test("billion range", () => {
		expect(formatCompactCurrency(1_234_567_890)).toBe("$1.23B");
	});

	test("million range with custom digits", () => {
		expect(formatCompactCurrency(987_654_321, { digits: 1 })).toBe("$987.7M");
	});

	test("thousand range", () => {
		expect(formatCompactCurrency(12_345)).toBe("$12.35K");
	});

	test("negative uses Unicode minus", () => {
		const out = formatCompactCurrency(-500_000_000);
		expect(out.startsWith(MINUS)).toBe(true);
		expect(out).toBe(`${MINUS}$500.00M`);
	});

	test("null / undefined / NaN / Infinity return em-dash", () => {
		expect(formatCompactCurrency(null)).toBe(EM_DASH);
		expect(formatCompactCurrency(undefined)).toBe(EM_DASH);
		expect(formatCompactCurrency(Number.NaN)).toBe(EM_DASH);
		expect(formatCompactCurrency(Number.POSITIVE_INFINITY)).toBe(EM_DASH);
	});

	test("EUR currency", () => {
		expect(formatCompactCurrency(2_500_000, { currency: "EUR" })).toBe("€2.50M");
	});

	test("zero formats cleanly", () => {
		expect(formatCompactCurrency(0)).toBe("$0.00");
	});
});

describe("formatPpDrift", () => {
	test("positive drift has + prefix", () => {
		expect(formatPpDrift(0.023)).toBe("+2.3pp");
	});

	test("negative drift uses Unicode minus", () => {
		expect(formatPpDrift(-0.011)).toBe(`${MINUS}1.1pp`);
	});

	test("zero has no sign", () => {
		expect(formatPpDrift(0)).toBe("0.0pp");
	});

	test("custom digits", () => {
		expect(formatPpDrift(0.0236, 2)).toBe("+2.36pp");
	});

	test("null / non-finite return em-dash", () => {
		expect(formatPpDrift(null)).toBe(EM_DASH);
		expect(formatPpDrift(undefined)).toBe(EM_DASH);
		expect(formatPpDrift(Number.NaN)).toBe(EM_DASH);
	});

	test("very small values", () => {
		expect(formatPpDrift(0.00001, 1)).toBe("+0.0pp");
	});
});

describe("formatMonoPercent", () => {
	test("positive percent", () => {
		expect(formatMonoPercent(0.1234)).toBe("12.34%");
	});

	test("negative uses Unicode minus", () => {
		expect(formatMonoPercent(-0.0005)).toBe(`${MINUS}0.05%`);
	});

	test("zero", () => {
		expect(formatMonoPercent(0)).toBe("0.00%");
	});

	test("custom digits", () => {
		expect(formatMonoPercent(0.1, 0)).toBe("10%");
	});

	test("null / non-finite return em-dash", () => {
		expect(formatMonoPercent(null)).toBe(EM_DASH);
		expect(formatMonoPercent(undefined)).toBe(EM_DASH);
		expect(formatMonoPercent(Number.POSITIVE_INFINITY)).toBe(EM_DASH);
	});
});
