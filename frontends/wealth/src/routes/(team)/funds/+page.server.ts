/** Fund universe — fetch all funds with optional filters. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	// Pass through query params as filters
	const block = url.searchParams.get("block");
	const geography = url.searchParams.get("geography");
	const asset_class = url.searchParams.get("asset_class");

	const params: Record<string, string> = {};
	if (block) params.block = block;
	if (geography) params.geography = geography;
	if (asset_class) params.asset_class = asset_class;

	const [funds, scoring] = await Promise.allSettled([
		api.get("/funds", params),
		api.get("/funds/scoring"),
	]);

	return {
		funds: funds.status === "fulfilled" ? funds.value : null,
		scoring: scoring.status === "fulfilled" ? scoring.value : null,
		filters: { block, geography, asset_class },
	};
};
