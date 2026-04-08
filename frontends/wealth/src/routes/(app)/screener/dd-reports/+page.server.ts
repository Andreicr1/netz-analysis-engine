/**
 * Legacy redirect — `/screener/dd-reports` → `/library`.
 *
 * Phase 7 of the Wealth Library sprint (spec §2.4). The DD Reports
 * pill in the Screener was removed and the entire reading workbench
 * moved into the Library. We keep this loader so that pasted Slack
 * links and bookmarked URLs still resolve via 308 instead of 404.
 *
 * 308 (not 301) is intentional: it tells crawlers and SvelteKit
 * clients that the redirect is permanent AND must preserve the
 * request method, which protects any tooling that does HEAD probes.
 */

import { redirect } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = () => {
	throw redirect(308, "/library");
};
