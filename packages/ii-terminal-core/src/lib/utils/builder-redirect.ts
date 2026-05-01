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
 * Build the destination URL string for the /portfolio/builder
 * redirect.
 *
 * Rules:
 *   - ``id`` is rewritten to ``portfolio_id`` (legacy wealth callers).
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
		if (key === "id") {
			destParams.set("portfolio_id", value);
			continue;
		}
		destParams.set(key, value);
	}

	const profile = normalizeProfile(resolvedProfile) ?? DEFAULT_PROFILE;
	return `/allocation/${profile}?${destParams.toString()}`;
}
