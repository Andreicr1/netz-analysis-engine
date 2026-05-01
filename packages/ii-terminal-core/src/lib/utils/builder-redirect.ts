/**
 * Pure helpers for the /portfolio/builder → /allocation/{profile}
 * redirect (PR-UX-2).
 *
 * Lives in ii-terminal-core (instead of co-located with the route)
 * so the redirect contract is unit testable via the package's vitest
 * harness, without requiring a vitest runner in frontends/terminal.
 */
import {
	ALLOCATION_PROFILES,
	type AllocationProfile,
} from "../types/allocation-page.js";

export const DEFAULT_PROFILE: AllocationProfile = "moderate";

export function isAllocationProfile(raw: string): raw is AllocationProfile {
	return (ALLOCATION_PROFILES as readonly string[]).includes(raw);
}

/**
 * Normalize an unknown profile string (case-insensitive) into the
 * canonical AllocationProfile or ``null`` if it isn't one we serve.
 */
export function normalizeProfile(
	raw: string | null | undefined,
): AllocationProfile | null {
	if (!raw) return null;
	const lower = raw.toLowerCase();
	return isAllocationProfile(lower) ? lower : null;
}

/**
 * Extract the canonical portfolio_id from a URLSearchParams, applying
 * the precedence rule shared by lookup and redirect emit:
 *
 *   1. First value of ``portfolio_id`` if present.
 *   2. Else first value of ``id`` (legacy wealth callers).
 *   3. Else ``null``.
 *
 * Centralizing this avoids the regression where the loader fetches
 * the profile for one id while the redirect carries another (e.g.
 * URL contains both ``?portfolio_id=B&id=A`` or repeated keys, which
 * would have been resolved differently by ``URLSearchParams.get``
 * vs. last-write-wins iteration in ``buildBuilderRedirect``).
 */
export function extractCanonicalPortfolioId(
	source: URLSearchParams,
): string | null {
	return source.get("portfolio_id") ?? source.get("id");
}

/**
 * Build the destination URL string for the /portfolio/builder
 * redirect.
 *
 * Rules:
 *   - ``portfolio_id`` is emitted exactly once, from the canonical
 *     value chosen by ``extractCanonicalPortfolioId`` — guaranteeing
 *     the redirect carries the same id the loader used for the
 *     profile lookup, regardless of source key order or duplicates.
 *   - Legacy ``id`` is dropped from the output (its value already
 *     contributes to the canonical id when no ``portfolio_id`` is
 *     present).
 *   - All other query params pass through untouched.
 *   - ``tab=portfolio`` is forced on the destination.
 *   - Destination profile is the resolved profile if valid, else
 *     ``DEFAULT_PROFILE`` (graceful degrade).
 */
export function buildBuilderRedirect(
	source: URLSearchParams,
	resolvedProfile: string | null,
): string {
	const destParams = new URLSearchParams();
	destParams.set("tab", "portfolio");

	for (const [key, value] of source) {
		// Strip both id keys — the canonical portfolio_id is emitted
		// once, after the iteration, from the precedence helper.
		if (key === "id" || key === "portfolio_id") continue;
		destParams.set(key, value);
	}

	const canonicalPortfolioId = extractCanonicalPortfolioId(source);
	if (canonicalPortfolioId) {
		destParams.set("portfolio_id", canonicalPortfolioId);
	}

	const profile = normalizeProfile(resolvedProfile) ?? DEFAULT_PROFILE;
	return `/allocation/${profile}?${destParams.toString()}`;
}
