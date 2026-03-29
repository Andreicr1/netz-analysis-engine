/**
 * Stale data detection per UX Principles.
 *
 * Freshness derived exclusively from server computed_at timestamps.
 * Date.now() is forbidden for freshness determination.
 *
 * Business days (Mon-Fri): stale if computed_at < 08:00 today (America/Sao_Paulo).
 * Weekends/holidays: stale if computed_at < 08:00 last Friday.
 */

const SAO_PAULO_TZ = "America/Sao_Paulo";

/**
 * Cached DateTimeFormat for São Paulo timezone.
 * eslint-disable-next-line: this is an internal timezone parser for business-day
 * staleness logic, not a display formatter. @investintell/ui formatters do not expose
 * timezone-aware current-time parsing, so direct Intl usage is required here.
 */
// eslint-disable-next-line no-restricted-syntax
const saoPauloFormatter = new Intl.DateTimeFormat("en-US", {
	timeZone: SAO_PAULO_TZ,
	year: "numeric",
	month: "2-digit",
	day: "2-digit",
	hour: "2-digit",
	minute: "2-digit",
	second: "2-digit",
	hour12: false,
});

/** Get current date/time in São Paulo timezone. */
function nowInSaoPaulo(): Date {
	return new Date(saoPauloFormatter.format(new Date()));
}

/** Get the 08:00 threshold for a given date in São Paulo. */
function threshold08(date: Date): Date {
	const d = new Date(date);
	d.setHours(8, 0, 0, 0);
	return d;
}

/** Find last Friday from a given date. */
function lastFriday(date: Date): Date {
	const d = new Date(date);
	const day = d.getDay();
	// 0=Sun, 1=Mon, ..., 5=Fri, 6=Sat
	const diff = day === 0 ? 2 : day === 6 ? 1 : day < 5 ? day + 2 : 0;
	d.setDate(d.getDate() - diff);
	return d;
}

/**
 * Check if data is stale based on server computed_at timestamp.
 *
 * Accepts either an ISO string (from server computed_at) or a Date object.
 * Freshness is always derived from the server timestamp, never from client time.
 */
export function isStale(computedAt: string | Date | null): boolean {
	if (!computedAt) return true;

	const lastUpdated = typeof computedAt === "string" ? new Date(computedAt) : computedAt;

	// Invalid date check
	if (isNaN(lastUpdated.getTime())) return true;

	const now = nowInSaoPaulo();
	const dayOfWeek = now.getDay(); // 0=Sun, 6=Sat

	if (dayOfWeek === 0 || dayOfWeek === 6) {
		// Weekend: stale if before 08:00 last Friday
		const fri = lastFriday(now);
		return lastUpdated < threshold08(fri);
	}

	// Business day: stale if before 08:00 today
	return lastUpdated < threshold08(now);
}

/** Format a server computed_at timestamp for display in stale banner. */
export function formatLastUpdated(computedAt: string | Date | null): string {
	if (!computedAt) return "never";

	const date = typeof computedAt === "string" ? new Date(computedAt) : computedAt;

	if (isNaN(date.getTime())) return "never";

	const now = new Date();
	const diffMs = now.getTime() - date.getTime();
	const diffHours = Math.floor(diffMs / (1000 * 60 * 60));

	if (diffHours < 1) return "just now";
	if (diffHours < 24) return `${diffHours}h ago`;

	const m = date.toISOString().slice(5, 7);
	const d = date.getDate();
	const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
	const hh = String(date.getHours()).padStart(2, "0");
	const mm = String(date.getMinutes()).padStart(2, "0");
	return `${months[parseInt(m, 10) - 1]} ${d}, ${hh}:${mm}`;
}
