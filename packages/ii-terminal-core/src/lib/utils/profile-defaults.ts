/**
 * Profile-differentiated CVaR defaults — mirrors the authoritative backend
 * helper ``app.domains.wealth.models.model_portfolio.default_cvar_limit_for_profile``
 * (PR-A18, recalibrated from A12.2). Keep the two in sync; a future PR may
 * expose these via an admin config endpoint so the frontend stops
 * duplicating the mapping.
 *
 * PR-BE-7 (2026-04-30) — ``aggressive`` was a development artefact and
 * is no longer a canonical profile. The slug is rewritten to ``growth``
 * with a console warning so any residual caller is visible during the
 * 180-day sunset window (target 2026-10-30).
 *
 * Unknown / null profile → 0.075 (moderate), matching the backend fallback.
 */
export function defaultCvarForProfile(profile: string | null | undefined): number {
	const raw = (profile ?? "").toLowerCase();
	const canonical = raw === "aggressive" ? "growth" : raw;
	if (raw === "aggressive") {
		console.warn(
			"[PR-BE-7] Legacy 'aggressive' profile received in defaultCvarForProfile; " +
				"normalised to 'growth'. Sunset 2026-10-30.",
		);
	}
	switch (canonical) {
		case "conservative":
			return 0.05; // PR-A18: was 0.025
		case "moderate":
			return 0.075; // PR-A18: was 0.05
		case "growth":
			return 0.1; // PR-A18: was 0.08 (Dynamic Growth)
		default:
			return 0.075; // moderate fallback (PR-A18)
	}
}

/**
 * Human label for the profile, used in UI copy.
 *
 * Prefer ``profileDisplayLabel`` from ``$lib/i18n/quant-labels`` when
 * the call site needs context-sensitive ("Dynamic" vs "Dynamic Growth")
 * phrasing — this helper is retained for legacy call sites that pass a
 * raw string straight into a chart title or table cell.
 */
export function profileLabel(profile: string | null | undefined): string {
	const raw = (profile ?? "").toLowerCase();
	const canonical = raw === "aggressive" ? "growth" : raw;
	if (canonical === "conservative") return "Conservative";
	if (canonical === "moderate") return "Balanced";
	if (canonical === "growth") return "Dynamic Growth";
	return profile ?? "Balanced";
}
