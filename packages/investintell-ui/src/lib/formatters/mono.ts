/**
 * Mono-friendly formatters for terminal surfaces.
 *
 * All outputs are tabular-safe (stable column widths) and
 * locale-independent. Callers in (terminal)/** and
 * lib/components/terminal/** must use these instead of
 * `.toFixed`, `.toLocaleString`, or `new Intl.*` — enforced by
 * the ESLint rule in frontends/eslint.config.js.
 *
 * Source of truth: docs/plans/2026-04-18-netz-terminal-parity.md §B.2.
 */

const EM_DASH = "\u2014";
const MINUS = "\u2212"; // Unicode minus for column alignment.

const compactCurrencyCache = new Map<string, Intl.NumberFormat>();

function compactCurrencyFormatter(currency: string, digits: number): Intl.NumberFormat {
	const key = `${currency}|${digits}`;
	const cached = compactCurrencyCache.get(key);
	if (cached) return cached;
	const formatter = new Intl.NumberFormat("en-US", {
		style: "currency",
		currency,
		notation: "compact",
		compactDisplay: "short",
		maximumFractionDigits: digits,
		minimumFractionDigits: digits,
	});
	compactCurrencyCache.set(key, formatter);
	return formatter;
}

function pad2(n: number): string {
	return n < 10 ? `0${n}` : String(n);
}

/**
 * UTC or local clock string "HH:MM:SS UTC". Zero allocation
 * beyond the Date itself.
 */
export function formatMonoTime(d: Date, kind: "utc" | "local" = "utc"): string {
	if (kind === "utc") {
		return `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}:${pad2(d.getUTCSeconds())} UTC`;
	}
	return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}

export interface CompactCurrencyOptions {
	digits?: number;
	currency?: "USD" | "EUR" | "BRL";
}

/**
 * Compact currency: $1.23B / $987M / $12.3K. Negative sign uses
 * Unicode minus. Returns "—" for null / undefined / non-finite.
 */
export function formatCompactCurrency(
	value: number | null | undefined,
	opts: CompactCurrencyOptions = {},
): string {
	if (value === null || value === undefined || !Number.isFinite(value)) {
		return EM_DASH;
	}
	const digits = opts.digits ?? 2;
	const currency = opts.currency ?? "USD";
	const formatted = compactCurrencyFormatter(currency, digits).format(Math.abs(value));
	return value < 0 ? `${MINUS}${formatted}` : formatted;
}

/**
 * Percentage-point drift: "+2.3pp", "−1.1pp", "0.0pp". Input is a
 * fraction (0.023 → "+2.3pp"). Uses Unicode minus for alignment.
 */
export function formatPpDrift(
	fractionDelta: number | null | undefined,
	digits: number = 1,
): string {
	if (fractionDelta === null || fractionDelta === undefined || !Number.isFinite(fractionDelta)) {
		return EM_DASH;
	}
	const pp = fractionDelta * 100;
	const abs = Math.abs(pp).toFixed(digits);
	if (pp > 0) return `+${abs}pp`;
	if (pp < 0) return `${MINUS}${abs}pp`;
	return `${abs}pp`;
}

/**
 * Terminal percent: "12.34%", "−0.05%". Input is a fraction.
 * Tabular-nums friendly.
 */
export function formatMonoPercent(
	fraction: number | null | undefined,
	digits: number = 2,
): string {
	if (fraction === null || fraction === undefined || !Number.isFinite(fraction)) {
		return EM_DASH;
	}
	const pct = fraction * 100;
	const abs = Math.abs(pct).toFixed(digits);
	return pct < 0 ? `${MINUS}${abs}%` : `${abs}%`;
}
