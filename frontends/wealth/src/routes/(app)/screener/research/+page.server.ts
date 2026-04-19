/**
 * Wealth shim — redirects /screener/research to the legacy /research route.
 *
 * Added in X2 (ii-terminal extraction) so the shared CommandPalette and
 * TerminalShell, which now call `resolve("/screener/research")`, typecheck
 * in wealth. The wealth-app /screener route (legacy Wealth Library suite)
 * owns the /screener prefix, so we cannot park this under (terminal) —
 * it would collide. Once X7 deletes (terminal) from wealth entirely
 * this shim stays (wealth still needs the typecheck) or is replaced
 * with a hard 404 depending on whether /research survives the cleanup.
 */
import { redirect } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = async ({ url }) => {
	const query = url.search;
	throw redirect(307, `/research${query}`);
};
