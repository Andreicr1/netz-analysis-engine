/**
 * Legacy redirect — `/screener/dd-reports/{fundId}` → `/library?q={fundId}`.
 *
 * Phase 7 of the Wealth Library sprint (spec §2.4). The fund-only
 * variant of the legacy DD Reports list has no canonical
 * Library URL — the documents now live under
 * `/library/due-diligence/by-fund/{slug}` and we cannot resolve the
 * slug without an extra round trip. The pragmatic fall-through is a
 * Library search seeded with the legacy `fundId`, which lands the
 * user on the right fund's documents in one step.
 */

import { redirect } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ params }) => {
	const fundId = params.fundId ?? "";
	throw redirect(
		308,
		fundId ? `/library?q=${encodeURIComponent(fundId)}` : "/library",
	);
};
