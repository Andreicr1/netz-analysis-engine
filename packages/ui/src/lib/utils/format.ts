/** Formatting utilities for Netz frontends. */

const EM_DASH = "—";
const numberFormatterCache = new Map<string, Intl.NumberFormat>();
const dateFormatterCache = new Map<string, Intl.DateTimeFormat>();
const relativeFormatterCache = new Map<string, Intl.RelativeTimeFormat>();

type NullableNumber = number | null | undefined;
type DateInput = Date | string | number | null | undefined;
type DateStyle = "short" | "medium" | "long" | "full";
type PLDirection = "up" | "down" | "flat";

interface FormatBpsOptions {
	decimals?: number;
	locale?: string;
	signed?: boolean;
}

function createFormatterCacheKey(
	locale: string,
	options: Intl.NumberFormatOptions | Intl.DateTimeFormatOptions | Intl.RelativeTimeFormatOptions,
): string {
	const serialized = Object.entries(options)
		.sort(([left], [right]) => left.localeCompare(right))
		.map(([key, value]) => `${key}:${String(value)}`)
		.join("|");

	return `${locale}|${serialized}`;
}

function getNumberFormatter(locale: string, options: Intl.NumberFormatOptions): Intl.NumberFormat {
	const key = createFormatterCacheKey(locale, options);
	const formatter = numberFormatterCache.get(key);

	if (formatter) {
		return formatter;
	}

	const nextFormatter = new Intl.NumberFormat(locale, options);
	numberFormatterCache.set(key, nextFormatter);
	return nextFormatter;
}

function getDateFormatter(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
	const key = createFormatterCacheKey(locale, options);
	const formatter = dateFormatterCache.get(key);

	if (formatter) {
		return formatter;
	}

	const nextFormatter = new Intl.DateTimeFormat(locale, options);
	dateFormatterCache.set(key, nextFormatter);
	return nextFormatter;
}

function getRelativeFormatter(
	locale: string,
	options: Intl.RelativeTimeFormatOptions,
): Intl.RelativeTimeFormat {
	const key = createFormatterCacheKey(locale, options);
	const formatter = relativeFormatterCache.get(key);

	if (formatter) {
		return formatter;
	}

	const nextFormatter = new Intl.RelativeTimeFormat(locale, options);
	relativeFormatterCache.set(key, nextFormatter);
	return nextFormatter;
}

function isFiniteNumber(value: NullableNumber): value is number {
	return typeof value === "number" && Number.isFinite(value);
}

function toDate(value: DateInput): Date | null {
	if (value == null) {
		return null;
	}

	const date = value instanceof Date ? value : new Date(value);
	return Number.isNaN(date.getTime()) ? null : date;
}

function formatNumericValue(
	value: NullableNumber,
	locale: string,
	options: Intl.NumberFormatOptions,
): string {
	if (!isFiniteNumber(value)) {
		return EM_DASH;
	}

	return getNumberFormatter(locale, options).format(value);
}

/**
 * Format a number as currency.
 * Default: USD with en-US locale.
 */
export function formatCurrency(
	value: NullableNumber,
	currency = "USD",
	locale = "en-US",
): string {
	return formatNumericValue(value, locale, {
		style: "currency",
		currency,
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
	});
}

/**
 * Format a number with fixed decimals.
 */
export function formatNumber(
	value: NullableNumber,
	decimals = 2,
	locale = "en-US",
	options: Intl.NumberFormatOptions = {},
): string {
	return formatNumericValue(value, locale, {
		minimumFractionDigits: decimals,
		maximumFractionDigits: decimals,
		...options,
	});
}

/**
 * Format a number as percentage. Input is a decimal (0.05 = 5%).
 */
export function formatPercent(
	value: NullableNumber,
	decimals = 2,
	locale = "en-US",
	signed = false,
): string {
	return formatNumericValue(value, locale, {
		style: "percent",
		minimumFractionDigits: decimals,
		maximumFractionDigits: decimals,
		signDisplay: signed ? "exceptZero" : "auto",
	});
}

/**
 * Format a number in compact notation (1.2M, 3.5K).
 */
export function formatCompact(value: NullableNumber, locale = "en-US"): string {
	return formatNumericValue(value, locale, {
		notation: "compact",
		maximumFractionDigits: 1,
	});
}

/**
 * Format assets under management in compact currency notation.
 */
export function formatAUM(
	value: NullableNumber,
	currency = "USD",
	locale = "en-US",
): string {
	return formatNumericValue(value, locale, {
		style: "currency",
		currency,
		notation: "compact",
		compactDisplay: "short",
		maximumFractionDigits: 1,
	});
}

/**
 * Format a basis-points value from a decimal fraction (0.015 = 150 bps).
 */
export function formatBps(
	value: NullableNumber,
	{ decimals = 0, locale = "en-US", signed = false }: FormatBpsOptions = {},
): string {
	if (!isFiniteNumber(value)) {
		return EM_DASH;
	}

	const formatted = formatNumber(value * 10_000, decimals, locale, {
		signDisplay: signed ? "exceptZero" : "auto",
	});
	return `${formatted} bps`;
}

/**
 * Format NAV-like values with 4 decimal places.
 */
export function formatNAV(
	value: NullableNumber,
	currency = "USD",
	locale = "en-US",
): string {
	return formatNumericValue(value, locale, {
		style: "currency",
		currency,
		minimumFractionDigits: 4,
		maximumFractionDigits: 4,
	});
}

/**
 * Format ratio values such as leverage or sharpe ("1.23x").
 */
export function formatRatio(
	value: NullableNumber,
	decimals = 2,
	suffix = "x",
	locale = "en-US",
): string {
	const formatted = formatNumber(value, decimals, locale);
	return formatted === EM_DASH ? formatted : `${formatted}${suffix}`;
}

/**
 * Format a date using Intl.DateTimeFormat.
 */
export function formatDate(
	date: DateInput,
	style: DateStyle = "medium",
	locale = "en-US",
): string {
	const resolvedDate = toDate(date);

	if (!resolvedDate) {
		return EM_DASH;
	}

	const styleMap: Record<DateStyle, Intl.DateTimeFormatOptions> = {
		short: { day: "2-digit", month: "2-digit", year: "2-digit" },
		medium: { day: "numeric", month: "short", year: "numeric" },
		long: { day: "numeric", month: "long", year: "numeric" },
		full: { weekday: "long", day: "numeric", month: "long", year: "numeric" },
	};

	return getDateFormatter(locale, styleMap[style]).format(resolvedDate);
}

/**
 * Format time-only (HH:MM, 24h). Used by compact terminal panels.
 */
export function formatTime(date: DateInput, locale = "en-US"): string {
	const resolvedDate = toDate(date);

	if (!resolvedDate) {
		return EM_DASH;
	}

	return getDateFormatter(locale, {
		hour: "2-digit",
		minute: "2-digit",
		hour12: false,
	}).format(resolvedDate);
}

/**
 * Format a date/time for audit surfaces.
 */
export function formatDateTime(date: DateInput, locale = "en-US"): string {
	const resolvedDate = toDate(date);

	if (!resolvedDate) {
		return EM_DASH;
	}

	return getDateFormatter(locale, {
		day: "2-digit",
		month: "short",
		year: "numeric",
		hour: "2-digit",
		minute: "2-digit",
		hour12: false,
	}).format(resolvedDate);
}

/**
 * Format a date range as "Jan 1 – Mar 15, 2026".
 */
export function formatDateRange(
	start: DateInput,
	end: DateInput,
	locale = "en-US",
): string {
	const startDate = toDate(start);
	const endDate = toDate(end);

	if (!startDate || !endDate) {
		return EM_DASH;
	}

	const sameYear = startDate.getFullYear() === endDate.getFullYear();

	const startOpts: Intl.DateTimeFormatOptions = sameYear
		? { day: "numeric", month: "short" }
		: { day: "numeric", month: "short", year: "numeric" };

	const endOpts: Intl.DateTimeFormatOptions = {
		day: "numeric",
		month: "short",
		year: "numeric",
	};

	const startStr = getDateFormatter(locale, startOpts).format(startDate);
	const endStr = getDateFormatter(locale, endOpts).format(endDate);

	return `${startStr} – ${endStr}`;
}

/**
 * Format a date relative to a reference time.
 */
export function formatRelativeDate(
	date: DateInput,
	locale = "en-US",
	now: DateInput = new Date(),
): string {
	const resolvedDate = toDate(date);
	const resolvedNow = toDate(now);

	if (!resolvedDate || !resolvedNow) {
		return EM_DASH;
	}

	const deltaMs = resolvedDate.getTime() - resolvedNow.getTime();
	const absoluteDeltaMs = Math.abs(deltaMs);

	const units: ReadonlyArray<[Intl.RelativeTimeFormatUnit, number]> = [
		["year", 1000 * 60 * 60 * 24 * 365],
		["month", 1000 * 60 * 60 * 24 * 30],
		["week", 1000 * 60 * 60 * 24 * 7],
		["day", 1000 * 60 * 60 * 24],
		["hour", 1000 * 60 * 60],
		["minute", 1000 * 60],
		["second", 1000],
	];

	for (const [unit, size] of units) {
		if (absoluteDeltaMs >= size || unit === "second") {
			return getRelativeFormatter(locale, { numeric: "auto" }).format(
				Math.round(deltaMs / size),
				unit,
			);
		}
	}

	return EM_DASH;
}

export function plDirection(value: NullableNumber): PLDirection {
	if (!isFiniteNumber(value) || value === 0) {
		return "flat";
	}

	return value > 0 ? "up" : "down";
}

export function plColor(value: NullableNumber): string {
	switch (plDirection(value)) {
		case "up":
			return "var(--netz-success)";
		case "down":
			return "var(--netz-danger)";
		default:
			return "var(--netz-text-secondary)";
	}
}

/**
 * Format a date as "DD/MM" for compact chart axes (e.g., "17/03").
 * Useful for DriftHistoryPanel and any chart with dense date labels.
 */
export function formatShortDate(date: DateInput, locale = "en-US"): string {
	const resolvedDate = toDate(date);

	if (!resolvedDate) {
		return EM_DASH;
	}

	return getDateFormatter(locale, { day: "2-digit", month: "2-digit" }).format(resolvedDate);
}

/**
 * Format ISIN with spaces: "BR XXXX XXXX XX".
 */
export function formatISIN(isin: string): string {
	const clean = isin.replace(/\s/g, "").toUpperCase();

	if (clean.length !== 12) {
		return clean;
	}

	return `${clean.slice(0, 2)} ${clean.slice(2, 6)} ${clean.slice(6, 10)} ${clean.slice(10)}`;
}
