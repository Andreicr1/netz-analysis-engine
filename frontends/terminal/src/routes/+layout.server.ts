/**
 * Root layout server loader — loads Actor + token for all terminal pages.
 *
 * X1 scaffold scope: just surface the verified actor/token from hooks.
 * X3 swaps `defaultDarkBranding` for ii-bundle branding; X4 removes
 * any residual Netz strings from chrome.
 */
import type { LayoutServerLoad } from "./$types";
import { defaultDarkBranding } from "@investintell/ui/utils";

/** Normalize Clerk role — strip "org:" prefix so frontend lists match. */
function normalizeRole(raw: string | null | undefined): string | null {
	if (!raw) return null;
	return raw.replace(/^org:/, "");
}

export const load: LayoutServerLoad = async ({ locals }) => {
	const { actor, token } = locals;

	const normalizedActor = actor
		? { ...actor, role: normalizeRole(actor.role) }
		: actor;

	return {
		actor: normalizedActor,
		token,
		branding: defaultDarkBranding,
	};
};
