/**
 * Wealth shim — redirects /live to the legacy /portfolio/live route.
 *
 * Added in X2 (ii-terminal extraction) so the shared TerminalTopNav and
 * TerminalShell, both of which now call `resolve("/live")`, typecheck
 * in wealth. Once X7 deletes (terminal) from wealth entirely this shim
 * is removed with everything else.
 *
 * Shim-not-copy: this does not duplicate the live workbench page, it
 * redirects to the existing wealth route. Wealth still serves the
 * workbench content at /portfolio/live.
 */
import { redirect } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = async ({ url }) => {
	const query = url.search;
	throw redirect(307, `/portfolio/live${query}`);
};
