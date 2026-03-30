/**
 * Root layout server loader — loads Actor + token for all pages.
 * Branding is a fixed design system (defaultDarkBranding) — no longer per-org.
 */
import type { LayoutServerLoad } from "./$types";
import { defaultDarkBranding } from "@investintell/ui/utils";

export const load: LayoutServerLoad = async ({ locals }) => {
	const { actor, token } = locals;

	return {
		actor,
		token,
		branding: defaultDarkBranding,
	};
};
