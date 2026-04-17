/**
 * Profile-differentiated CVaR defaults — mirrors the authoritative backend
 * helper ``app.domains.wealth.models.model_portfolio.default_cvar_limit_for_profile``
 * (PR-A18, recalibrated from A12.2). Keep the two in sync; a future PR may
 * expose these via an admin config endpoint so the frontend stops
 * duplicating the mapping.
 *
 * Unknown / null profile → 0.075 (moderate), matching the backend fallback.
 */
export function defaultCvarForProfile(profile: string | null | undefined): number {
	switch ((profile ?? "").toLowerCase()) {
		case "conservative":
			return 0.05; // PR-A18: was 0.025
		case "moderate":
			return 0.075; // PR-A18: was 0.05
		case "growth":
			return 0.1; // PR-A18: was 0.08
		case "aggressive":
			return 0.125; // PR-A18: was 0.1
		default:
			return 0.075; // moderate fallback (PR-A18)
	}
}

/** Human label for the profile, used in UI copy. */
export function profileLabel(profile: string | null | undefined): string {
	const p = (profile ?? "").toLowerCase();
	if (p === "conservative") return "Conservative";
	if (p === "moderate") return "Moderate";
	if (p === "growth") return "Growth";
	if (p === "aggressive") return "Aggressive";
	return profile ?? "Moderate";
}
