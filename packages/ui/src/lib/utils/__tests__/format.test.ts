import { describe, expect, it } from "vitest";
import {
	formatAUM,
	formatBps,
	formatCompact,
	formatCurrency,
	formatDate,
	formatDateTime,
	formatISIN,
	formatNAV,
	formatNumber,
	formatPercent,
	formatRatio,
	formatRelativeDate,
	plColor,
	plDirection,
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

	it("returns an em dash for null values", () => {
		expect(formatCurrency(null, "BRL", "pt-BR")).toBe("—");
	});
});

describe("formatNumber", () => {
	it("formats generic numeric values", () => {
		expect(formatNumber(1234.567, 2, "en-US")).toBe("1,234.57");
	});
});

describe("formatPercent", () => {
	it("formats percentage with locale-aware separators", () => {
		expect(formatPercent(0.1234, 2, "pt-BR")).toBe("12,34%");
	});

	it("formats signed percentage when requested", () => {
		expect(formatPercent(0.1234, 1, "en-US", true)).toBe("+12.3%");
	});
});

describe("formatCompact", () => {
	it("formats large numbers", () => {
		const result = formatCompact(1_500_000);
		expect(result.length).toBeLessThan(10);
	});
});

describe("formatAUM", () => {
	it("formats compact currency values", () => {
		expect(formatAUM(1_200_000_000, "USD", "en-US")).toContain("1.2");
	});
});

describe("formatBps", () => {
	it("formats decimal values as basis points", () => {
		expect(formatBps(0.015)).toBe("150 bps");
	});

	it("supports signed output", () => {
		expect(formatBps(-0.0025, { signed: true })).toBe("-25 bps");
	});
});

describe("formatNAV", () => {
	it("formats NAV values with four decimals", () => {
		expect(formatNAV(1234.56789, "USD", "en-US")).toBe("$1,234.5679");
	});
});

describe("formatRatio", () => {
	it("formats ratio values with suffix", () => {
		expect(formatRatio(1.234, 2, "x", "en-US")).toBe("1.23x");
	});
});

describe("formatDate", () => {
	it("formats dates with the requested style", () => {
		expect(formatDate("2026-03-17T14:30:00Z", "medium", "en-US")).toBe("Mar 17, 2026");
	});

	it("returns an em dash for invalid dates", () => {
		expect(formatDate("invalid-date", "medium", "en-US")).toBe("—");
	});
});

describe("formatDateTime", () => {
	it("formats audit-style timestamps", () => {
		expect(formatDateTime("2026-03-17T14:30:00", "en-US")).toBe("Mar 17, 2026, 14:30");
	});
});

describe("formatRelativeDate", () => {
	it("formats relative dates from a fixed reference point", () => {
		expect(
			formatRelativeDate("2026-03-15T12:00:00Z", "en-US", "2026-03-17T12:00:00Z"),
		).toBe("2 days ago");
	});
});

describe("P&L helpers", () => {
	it("maps direction from numeric values", () => {
		expect(plDirection(10)).toBe("up");
		expect(plDirection(-10)).toBe("down");
		expect(plDirection(0)).toBe("flat");
	});

	it("maps color tokens from numeric values", () => {
		expect(plColor(1)).toBe("var(--netz-success)");
		expect(plColor(-1)).toBe("var(--netz-danger)");
		expect(plColor(0)).toBe("var(--netz-text-secondary)");
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
