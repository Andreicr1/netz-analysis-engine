/** Formatting utilities for Netz frontends. */

/**
 * Format a number as currency.
 * Default: BRL with pt-BR locale.
 */
export function formatCurrency(
	value: number,
	currency = "BRL",
	locale = "pt-BR",
): string {
	return new Intl.NumberFormat(locale, {
		style: "currency",
		currency,
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
	}).format(value);
}

/**
 * Format a number as percentage.
 * Input is a decimal (0.05 = 5%). If the value is already in percent form (> 1 or < -1),
 * pass it as-is and set `decimals` accordingly.
 */
export function formatPercent(value: number, decimals = 2): string {
	return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * Format a number in compact notation (1.2M, 3.5K).
 */
export function formatCompact(value: number, locale = "en-US"): string {
	return new Intl.NumberFormat(locale, {
		notation: "compact",
		maximumFractionDigits: 1,
	}).format(value);
}

/**
 * Format a date using Intl.DateTimeFormat.
 * @param date - Date object or ISO string
 * @param style - 'short' | 'medium' | 'long' | 'full'
 */
export function formatDate(
	date: Date | string,
	style: "short" | "medium" | "long" | "full" = "medium",
	locale = "pt-BR",
): string {
	const d = typeof date === "string" ? new Date(date) : date;

	const styleMap: Record<string, Intl.DateTimeFormatOptions> = {
		short: { day: "2-digit", month: "2-digit", year: "2-digit" },
		medium: { day: "numeric", month: "short", year: "numeric" },
		long: { day: "numeric", month: "long", year: "numeric" },
		full: { weekday: "long", day: "numeric", month: "long", year: "numeric" },
	};

	return new Intl.DateTimeFormat(locale, styleMap[style]).format(d);
}

/**
 * Format a date range as "Jan 1 - Mar 15, 2026".
 */
export function formatDateRange(
	start: Date | string,
	end: Date | string,
	locale = "pt-BR",
): string {
	const s = typeof start === "string" ? new Date(start) : start;
	const e = typeof end === "string" ? new Date(end) : end;

	const sameYear = s.getFullYear() === e.getFullYear();

	const startOpts: Intl.DateTimeFormatOptions = sameYear
		? { day: "numeric", month: "short" }
		: { day: "numeric", month: "short", year: "numeric" };

	const endOpts: Intl.DateTimeFormatOptions = {
		day: "numeric",
		month: "short",
		year: "numeric",
	};

	const startStr = new Intl.DateTimeFormat(locale, startOpts).format(s);
	const endStr = new Intl.DateTimeFormat(locale, endOpts).format(e);

	return `${startStr} \u2013 ${endStr}`;
}

/**
 * Format ISIN with spaces: "BR XXXX XXXX XX".
 */
export function formatISIN(isin: string): string {
	const clean = isin.replace(/\s/g, "").toUpperCase();
	if (clean.length !== 12) return clean;
	return `${clean.slice(0, 2)} ${clean.slice(2, 6)} ${clean.slice(6, 10)} ${clean.slice(10)}`;
}
