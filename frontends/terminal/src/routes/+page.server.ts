/**
 * Root redirect — II Terminal boots into the Live workbench.
 *
 * /live (F1) is the institutional default landing once the operator
 * signs in. The TerminalTopNav F-key order (LIVE → SCREENER → MACRO →
 * BUILDER → DD → ALERTS) anchors on F1.
 */
import { redirect } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = async () => {
	throw redirect(307, "/live");
};
