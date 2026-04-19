/**
 * PR-A26.3 Section H — Profile list page loader.
 *
 * Parallel-fetches each profile's strategic-allocation summary so the
 * card grid renders approval status previews. Per-profile failures
 * surface as a summary with error set; they do not block the page.
 */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$wealth/api/client";
import {
	ALLOCATION_PROFILES,
	type AllocationProfile,
	type StrategicAllocationResponse,
} from "$wealth/types/allocation-page";

export type ProfileSummary = {
	profile: AllocationProfile;
	cvar_limit: number | null;
	has_active_approval: boolean;
	last_approved_at: string | null;
	last_approved_by: string | null;
	error: string | null;
};

export const load: PageServerLoad = async ({ parent }): Promise<{
	summaries: ProfileSummary[];
}> => {
	const { token } = await parent();
	if (!token) return { summaries: [] };

	const api = createServerApiClient(token);

	const summaries = await Promise.all(
		ALLOCATION_PROFILES.map(async (profile): Promise<ProfileSummary> => {
			try {
				const resp = await api.get<StrategicAllocationResponse>(
					`/portfolio/profiles/${profile}/strategic-allocation`,
				);
				return {
					profile,
					cvar_limit: resp.cvar_limit,
					has_active_approval: resp.has_active_approval,
					last_approved_at: resp.last_approved_at,
					last_approved_by: resp.last_approved_by,
					error: null,
				};
			} catch (err) {
				return {
					profile,
					cvar_limit: null,
					has_active_approval: false,
					last_approved_at: null,
					last_approved_by: null,
					error: err instanceof Error ? err.message : "Failed to load",
				};
			}
		}),
	);

	return { summaries };
};
