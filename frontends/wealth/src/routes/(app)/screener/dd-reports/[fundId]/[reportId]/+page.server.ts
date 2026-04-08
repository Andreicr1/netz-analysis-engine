/**
 * Legacy redirect — `/screener/dd-reports/{fundId}/{reportId}` →
 * `/library/due-diligence/by-fund/{slug}/v{version}`.
 *
 * Phase 7 of the Wealth Library sprint (spec §2.4 + §4.6). The
 * loader hits the backend resolver
 * `GET /library/redirect-dd-report/{fundId}/{reportId}` which
 * returns a 308 with the canonical Library deep link. We capture
 * the response WITHOUT following it (`redirect: "manual"`) so we
 * can re-emit the redirect from the SvelteKit layer with the same
 * Location and 308 status.
 *
 * Failure modes
 * -------------
 * The backend resolver answers a soft-fall 308 to `/library` for
 * archived reports. We treat any non-redirect status as a hard
 * failure and fall through to `/library?q={fundId}` so the user
 * still lands somewhere useful instead of seeing a 404.
 */

import { redirect } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

const API_BASE =
	import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export const load: PageServerLoad = async ({ parent, params, fetch }) => {
	const { token } = await parent();
	const fundId = params.fundId!;
	const reportId = params.reportId!;

	try {
		const response = await fetch(
			`${API_BASE}/library/redirect-dd-report/${fundId}/${reportId}`,
			{
				method: "GET",
				headers: {
					Authorization: `Bearer ${token}`,
				},
				redirect: "manual",
			},
		);

		// 308 (or any 3xx) → forward the canonical Library URL.
		if (response.status >= 300 && response.status < 400) {
			const location = response.headers.get("location");
			if (location) {
				throw redirect(308, location);
			}
		}
	} catch (err: unknown) {
		// `redirect()` throws a special HttpError-like object — let it
		// propagate so SvelteKit emits the 308 cleanly. Anything else
		// falls through to the search-based fallback below.
		if (
			err &&
			typeof err === "object" &&
			"status" in err &&
			"location" in err
		) {
			throw err;
		}
	}

	// Resolver failed or returned no Location — fall through to a
	// Library search seeded with the legacy fund id so the user still
	// lands somewhere coherent.
	throw redirect(
		308,
		fundId ? `/library?q=${encodeURIComponent(fundId)}` : "/library",
	);
};
