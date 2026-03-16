import { describe, it, expect } from "vitest";
import {
	formatCurrency,
	formatPercent,
	formatCompact,
	formatISIN,
} from "../format.js";

describe("formatCurrency", () => {
	it("formats BRL currency", () => {
		const result = formatCurrency(1234.56, "BRL", "pt-BR");
		expect(result).toContain("1.234,56");
	});

	it("formats USD currency", () => {
		const result = formatCurrency(1234.56, "USD", "en-US");
		expect(result).toContain("1,234.56");
	});
});

describe("formatPercent", () => {
	it("formats percentage", () => {
		const result = formatPercent(0.1234, 2);
		expect(result).toContain("12");
	});
});

describe("formatCompact", () => {
	it("formats large numbers", () => {
		const result = formatCompact(1_500_000);
		// Compact notation varies by locale but should shorten
		expect(result.length).toBeLessThan(10);
	});
});

describe("formatISIN", () => {
	it("formats 12-char ISIN with spaces", () => {
		const result = formatISIN("BRXXXX123456");
		expect(result).toBe("BR XXXX 1234 56");
	});

	it("returns input if not 12 chars", () => {
		expect(formatISIN("SHORT")).toBe("SHORT");
	});
});
