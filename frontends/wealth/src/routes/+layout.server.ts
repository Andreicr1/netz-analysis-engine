/**
 * Root layout server loader — loads Actor + branding for all pages.
 * Branding is fetched from GET /api/v1/branding with fallback to defaults.
 */
import type { LayoutServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import { defaultDarkBranding } from "@investintell/ui/utils";
import type { BrandingConfig } from "@investintell/ui/utils";
export const load: LayoutServerLoad = async ({ locals }) => {
	const { actor, token } = locals;

	// Fetch branding with fallback
	let branding: BrandingConfig;
	try {
		const api = createServerApiClient(token);
		branding = await api.get<BrandingConfig>("/branding", { vertical: "wealth" });
	} catch {
		branding = defaultDarkBranding;
	}

	return {
		actor,
		token,
		branding,
	};
};
