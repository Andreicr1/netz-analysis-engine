import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const activeTab = url.searchParams.get("tab") || "managers";
	const page = parseInt(url.searchParams.get("page") || "1");
	const pageSize = parseInt(url.searchParams.get("page_size") || "25");
	const search = url.searchParams.get("search") || "";
	const country = url.searchParams.get("country") || "";
	const domicile = url.searchParams.get("domicile") || "";
	const fundType = url.searchParams.get("type") || "";

	const [managersResult, fundsResult] = await Promise.allSettled([
		activeTab === "managers"
			? api.get(
					`/esma/managers?page=${page}&page_size=${pageSize}&search=${encodeURIComponent(search)}&country=${encodeURIComponent(country)}`,
				)
			: Promise.resolve(null),
		activeTab === "funds"
			? api.get(
					`/esma/funds?page=${page}&page_size=${pageSize}&search=${encodeURIComponent(search)}&domicile=${encodeURIComponent(domicile)}&type=${encodeURIComponent(fundType)}`,
				)
			: Promise.resolve(null),
	]);

	return {
		managers: managersResult.status === "fulfilled" ? managersResult.value : null,
		funds: fundsResult.status === "fulfilled" ? fundsResult.value : null,
		activeTab,
		currentParams: Object.fromEntries(url.searchParams.entries()),
	};
};
