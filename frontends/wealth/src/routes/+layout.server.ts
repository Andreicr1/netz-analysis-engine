/**
 * Root layout server loader — loads Actor + token for all pages.
 * Branding is a fixed design system (defaultDarkBranding) — no longer per-org.
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
