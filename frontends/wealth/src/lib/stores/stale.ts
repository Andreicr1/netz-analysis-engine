/**
 * Stale data detection per UX Principles.
 *
 * Business days (Mon-Fri): stale if lastUpdated < 08:00 today (America/Sao_Paulo).
 * Weekends/holidays: stale if lastUpdated < 08:00 last Friday.
 */

const SAO_PAULO_TZ = "America/Sao_Paulo";

/** Get current date/time in São Paulo timezone. */
function nowInSaoPaulo(): Date {
	return new Date(new Date().toLocaleString("en-US", { timeZone: SAO_PAULO_TZ }));
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

/** Check if data is stale based on lastUpdated timestamp. */
export function isStale(lastUpdated: Date | null): boolean {
	if (!lastUpdated) return true;

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

/** Format a Date for display in stale banner. */
export function formatLastUpdated(date: Date | null): string {
	if (!date) return "never";
	const now = new Date();
	const diffMs = now.getTime() - date.getTime();
	const diffHours = Math.floor(diffMs / (1000 * 60 * 60));

	if (diffHours < 1) return "just now";
	if (diffHours < 24) return `${diffHours}h ago`;

	return date.toLocaleDateString("en-US", {
		month: "short",
		day: "numeric",
		hour: "2-digit",
		minute: "2-digit",
	});
}
