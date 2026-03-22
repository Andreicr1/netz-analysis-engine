/** Portfolio profile workbench — snapshot + allocations. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { PortfolioSummary, PortfolioSnapshot, StrategicAllocation, EffectiveAllocation } from "$lib/types/portfolio";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const profile = params.profile!;

	const [portfolio, snapshot, strategic, effective] = await Promise.all([
		api.get<PortfolioSummary>(`/portfolios/${profile}`).catch(() => null),
		api.get<PortfolioSnapshot>(`/portfolios/${profile}/snapshot`).catch(() => null),
		api.get<StrategicAllocation[]>(`/allocation/${profile}/strategic`).catch(() => [] as StrategicAllocation[]),
		api.get<EffectiveAllocation[]>(`/allocation/${profile}/effective`).catch(() => [] as EffectiveAllocation[]),
	]);

	return { profile, portfolio, snapshot, strategic, effective };
};
