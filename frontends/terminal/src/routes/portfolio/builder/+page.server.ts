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
 * Profile resolution from ``?id=``: not performed here. Looking up
 * the portfolio's profile would require an extra authenticated round
 * trip on every redirect, and the new workspace does not yet surface
 * a per-portfolio profile filter. Redirecting to /allocation/moderate
 * is acceptable — users can switch profiles via the ProfileStrip on
 * arrival. Documented in the X3.1 PR body.
 */
import { redirect } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = async ({ url }) => {
	const dest = new URL("/allocation/moderate", url.origin);
	dest.searchParams.set("tab", "portfolio");

	for (const [key, value] of url.searchParams) {
		if (key === "id") {
			// Legacy name on wealth call sites — normalize to portfolio_id
			// so the new workspace's PortfolioTabContent picks it up.
			dest.searchParams.set("portfolio_id", value);
			continue;
		}
		dest.searchParams.set(key, value);
	}

	throw redirect(307, dest.pathname + dest.search);
};
