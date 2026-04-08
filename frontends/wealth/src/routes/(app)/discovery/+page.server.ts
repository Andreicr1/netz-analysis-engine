/**
 * Discovery page server load.
 *
 * Kept minimal: only extracts URL search params so the page component
 * can restore the FCL state on SSR. The actual managers fetch happens
 * client-side via `fetchManagers(getToken, ...)` in the orchestrator's
 * `$effect`, because Clerk auth tokens are only available in the
 * browser context (via `getContext("netz:getToken")`).
 */
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = async ({ url }) => {
	return {
		preselectedManagerId: url.searchParams.get("manager"),
		preselectedFundId: url.searchParams.get("fund"),
	};
};
