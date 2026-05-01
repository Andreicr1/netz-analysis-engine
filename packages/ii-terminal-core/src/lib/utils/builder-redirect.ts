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
 * RFC 4122 UUID (v1–v5, any version digit, any variant). The
 * /model-portfolios endpoint always issues UUIDs as ids, so anything
 * that isn't a UUID is either malformed or a path-traversal attempt
 * (e.g. ``..``, ``foo/bar``, ``%2e%2e``) and must NOT be interpolated
 * into the API path or echoed into the redirect destination.
 */
const UUID_RE =
	/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isValidPortfolioId(
	raw: string | null | undefined,
): raw is string {
	return typeof raw === "string" && UUID_RE.test(raw);
}

/**
 * Extract the canonical portfolio_id from a URLSearchParams, applying
 * the precedence rule shared by lookup and redirect emit:
 *
 *   1. First value of ``portfolio_id`` if present AND a valid UUID.
 *   2. Else first value of ``id`` (legacy wealth callers) if a valid
 *      UUID.
 *   3. Else ``null``.
 *
 * Centralizing this avoids two regressions:
 *   - Loader and redirect drifting on which id is canonical when both
 *     keys are present or repeated (P2 hotfix #1).
 *   - Crafted ids containing path separators (``..``, ``/``, encoded
 *     equivalents) reaching ``/model-portfolios/${id}`` and triggering
 *     authenticated GETs against unrelated backend routes (P2 hotfix
 *     #2). UUID validation here means both the lookup and the
 *     redirect emit ignore non-UUID values entirely.
 */
export function extractCanonicalPortfolioId(
	source: URLSearchParams,
): string | null {
	// Try each candidate key in precedence order and return the first
	// VALID UUID. We deliberately fall through on a present-but-invalid
	// portfolio_id so that a malformed canonical key doesn't shadow a
	// usable legacy id — e.g. ``?portfolio_id=garbage&id=<uuid>`` still
	// resolves to <uuid> instead of dropping both. Any non-UUID input is
	// rejected entirely, so this fallback can never widen the
	// path-traversal attack surface.
	for (const candidate of [
		source.get("portfolio_id"),
		source.get("id"),
	]) {
		if (isValidPortfolioId(candidate)) return candidate;
	}
	return null;
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
