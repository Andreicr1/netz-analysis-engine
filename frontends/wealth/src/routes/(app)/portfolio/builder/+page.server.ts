/** Allocation — SSR data for AllocationView (strategic/tactical/effective). */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

interface BlockMeta {
	block_id: string;
	display_name: string;
	geography: string;
	asset_class: string;
}

interface StrategicRow {
	block: string;
	weight: number;
	min_weight: number | null;
	max_weight: number | null;
}

interface TacticalRow {
	block: string;
	overweight: number;
	conviction: number | null;
}

interface EffectiveRow {
	block: string;
	strategic_weight: number;
	tactical_overweight: number;
	effective_weight: number;
}

const VALID_PROFILES = ["conservative", "moderate", "growth"] as const;

export const load: PageServerLoad = async (event) => {
	const { token } = await event.parent();
	const rawProfile = event.url.searchParams.get("profile") ?? "moderate";
	const profile = VALID_PROFILES.includes(rawProfile as typeof VALID_PROFILES[number])
		? rawProfile
		: "moderate";

	if (!token) {
		return {
			blocks: [] as BlockMeta[],
			strategic: [] as StrategicRow[],
			tactical: [] as TacticalRow[],
			effective: [] as EffectiveRow[],
			profile,
		};
	}

	const api = createServerApiClient(token);

	const [blocks, strategic, tactical, effective] = await Promise.all([
		api.get<BlockMeta[]>("/blended-benchmarks/blocks").catch(() => [] as BlockMeta[]),
		api.get<StrategicRow[]>(`/allocation/${profile}/strategic`).catch(() => [] as StrategicRow[]),
		api.get<TacticalRow[]>(`/allocation/${profile}/tactical`).catch(() => [] as TacticalRow[]),
		api.get<EffectiveRow[]>(`/allocation/${profile}/effective`).catch(() => [] as EffectiveRow[]),
	]);

	return { blocks, strategic, tactical, effective, profile };
};
