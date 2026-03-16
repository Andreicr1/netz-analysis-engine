/**
 * Root layout server loader — loads Actor + branding for all pages.
 * Branding is fetched from GET /api/v1/branding with fallback to defaults.
 */
import type { LayoutServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import { defaultBranding } from "@netz/ui/utils";
import type { BrandingConfig } from "@netz/ui/utils";

export const load: LayoutServerLoad = async ({ locals }) => {
	const { actor, token } = locals;

	// Fetch branding with fallback
	let branding: BrandingConfig;
	try {
		const api = createServerApiClient(token);
		branding = await api.get<BrandingConfig>("/branding", { vertical: "credit" });
	} catch {
		branding = defaultBranding;
	}

	return {
		actor,
		token,
		branding,
	};
};
