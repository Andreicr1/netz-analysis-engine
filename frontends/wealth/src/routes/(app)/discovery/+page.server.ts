/**
 * Discovery page server load.
 *
 * Fetches the initial managers list via the internal API proxy so the
 * first paint is already populated. Uses the RouteData<T>-style shape
 * (status: 'ok' | 'error') instead of `throw error()` so the page can
 * render a panel error state without tripping the global error boundary.
 */
import type { PageServerLoad } from "./$types";

interface ManagersResponse {
	rows: unknown[];
	next_cursor?: string | null;
}

export const load: PageServerLoad = async ({ fetch, url }) => {
	const res = await fetch("/api/v1/wealth/discovery/managers", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ filters: {}, limit: 50 }),
	});
	if (!res.ok) {
		return {
			status: "error" as const,
			error: `managers load: ${res.status}`,
			initialManagers: [],
			nextCursor: null,
			preselectedManagerId: url.searchParams.get("manager"),
			preselectedFundId: url.searchParams.get("fund"),
		};
	}
	const body = (await res.json()) as ManagersResponse;
	return {
		status: "ok" as const,
		initialManagers: body.rows,
		nextCursor: body.next_cursor ?? null,
		preselectedManagerId: url.searchParams.get("manager"),
		preselectedFundId: url.searchParams.get("fund"),
	};
};
