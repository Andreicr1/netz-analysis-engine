/**
 * Root layout server loader — loads Actor + branding for all pages.
 * Admin uses liquid_funds vertical for branding (cross-vertical dashboard).
 */
import type { LayoutServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import { defaultBranding } from "@netz/ui/utils";
import type { BrandingConfig } from "@netz/ui/utils";

export const load: LayoutServerLoad = async ({ locals }) => {
	const { actor, token } = locals;

	let branding: BrandingConfig;
	try {
		const api = createServerApiClient(token);
		branding = await api.get<BrandingConfig>("/branding", { vertical: "liquid_funds" });
	} catch {
		branding = defaultBranding;
	}

	return {
		actor,
		token,
		branding,
	};
};
