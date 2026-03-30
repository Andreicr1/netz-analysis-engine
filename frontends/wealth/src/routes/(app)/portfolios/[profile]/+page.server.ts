/** Portfolio profile workbench — snapshot + allocations + model portfolio fund breakdown. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { PortfolioSummary, PortfolioSnapshot, StrategicAllocation, EffectiveAllocation } from "$lib/types/portfolio";
import type { ModelPortfolio } from "$lib/types/model-portfolio";

interface BlockInfo {
	block_id: string;
	display_name: string;
}

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const profile = params.profile!;

	const [portfolio, snapshot, strategic, effective, blocks, modelPortfolios] = await Promise.all([
		api.get<PortfolioSummary>(`/portfolios/${profile}`).catch(() => null),
		api.get<PortfolioSnapshot>(`/portfolios/${profile}/snapshot`).catch(() => null),
		api.get<StrategicAllocation[]>(`/allocation/${profile}/strategic`).catch(() => [] as StrategicAllocation[]),
		api.get<EffectiveAllocation[]>(`/allocation/${profile}/effective`).catch(() => [] as EffectiveAllocation[]),
		api.get<BlockInfo[]>(`/blended-benchmarks/blocks`).catch(() => [] as BlockInfo[]),
		api.get<ModelPortfolio[]>("/model-portfolios").catch(() => [] as ModelPortfolio[]),
	]);

	const blockLabels: Record<string, string> = {};
	for (const b of blocks ?? []) blockLabels[b.block_id] = b.display_name;

	// Find the active model portfolio for this profile
	const modelPortfolio = modelPortfolios.find((mp) => mp.profile === profile) ?? null;

	return { profile, portfolio, snapshot, strategic, effective, blockLabels, modelPortfolio };
};
