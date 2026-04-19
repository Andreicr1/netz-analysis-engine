/**
 * X3.1 Builder Workspace — /allocation redirect.
 *
 * The legacy 3-card landing has been absorbed into the unified
 * /allocation/[profile] workspace. Visitors to the bare /allocation
 * route are redirected to /allocation/moderate (STRATEGIC tab by
 * default). The profile strip inside the workspace handles further
 * switches without a full page reload.
 */
import { redirect } from "@sveltejs/kit";

export const load = (): never => {
	throw redirect(307, "/allocation/moderate");
};
