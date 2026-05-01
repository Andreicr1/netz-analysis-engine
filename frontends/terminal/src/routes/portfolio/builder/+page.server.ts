/**
 * X3.1 Builder Workspace — /portfolio/builder → /allocation redirect.
 *
 * The builder workspace has been fused into /allocation/[profile]
 * as the PORTFOLIO tab. This route is redirect-only, preserving:
 *
 *   - ``?id=<uuid>`` → rewritten as ``?portfolio_id=<uuid>`` for the
 *     new workspace, which uses that param to override the default
 *     auto-select of portfolios[0]. That keeps deep links from
 *     wealth's TerminalBreadcrumb / ImpactPreview / TerminalShell
 *     landing the user on the right model.
 *   - every other ``?foo=bar`` pair → copied through untouched, so
 *     wealth's "&alloc=<profile>" badge etc. survive the hop.
 *   - ``?tab=portfolio`` → forced on the destination so users land
 *     on the builder surface, not the strategic governance tab.
 *
 * PR-UX-2: profile resolution from ``?portfolio_id=<uuid>`` (or the
 * legacy ``?id=<uuid>``). When a portfolio_id is present, fetch
 * ``/model-portfolios/{id}`` to resolve the portfolio's profile and
 * redirect into ``/allocation/{profile}`` instead of always landing
 * on /allocation/moderate. Falls back to ``/allocation/moderate`` if
 * the lookup fails (no token, fetch error, missing/invalid profile)
 * — graceful degrade so a transient API blip never blocks the route.
 */
import { redirect } from "@sveltejs/kit";
import { createServerApiClient } from "@investintell/ii-terminal-core/api/client";
import type { ModelPortfolio } from "@investintell/ii-terminal-core/types/model-portfolio";
import type { PageServerLoad } from "./$types";
import {
	DEFAULT_PROFILE,
	buildBuilderRedirect,
	extractCanonicalPortfolioId,
} from "@investintell/ii-terminal-core/utils/builder-redirect";

const FETCH_TIMEOUT_MS = 4000;

/**
 * Lookup a portfolio's profile by id. Returns ``null`` on any failure
 * — caller falls back to ``DEFAULT_PROFILE``.
 */
async function fetchPortfolioProfile(
	token: string,
	portfolioId: string,
): Promise<string | null> {
	try {
		const api = createServerApiClient(token);
		const portfolio = await api.get<ModelPortfolio>(
			`/model-portfolios/${portfolioId}`,
			undefined,
			{ signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
		);
		return portfolio?.profile ?? null;
	} catch {
		return null;
	}
}

export const load: PageServerLoad = async ({ url, parent }) => {
	const { token } = await parent();

	// Resolve the canonical id via the same helper buildBuilderRedirect
	// uses to emit it — guaranteeing lookup and redirect agree even if
	// the URL contains both ?portfolio_id= and ?id=, or repeated keys.
	const portfolioId = extractCanonicalPortfolioId(url.searchParams);

	let resolvedProfile: string | null = null;
	if (portfolioId && token) {
		resolvedProfile = await fetchPortfolioProfile(token, portfolioId);
	}

	const dest = buildBuilderRedirect(url.searchParams, resolvedProfile);
	throw redirect(307, dest);
};

// Re-export so deep-link debugging tools can introspect the fallback
// profile without re-importing the helper module directly.
export { DEFAULT_PROFILE };
