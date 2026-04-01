/** Legacy route — redirects to /analytics/[entityId]. */
import type { PageServerLoad } from "./$types";
import { redirect } from "@sveltejs/kit";

export const load: PageServerLoad = async ({ url }) => {
	const entityId = url.searchParams.get("entity_id");
	if (!entityId) {
		redirect(302, "/screener");
	}

	const window = url.searchParams.get("window");
	const benchmarkId = url.searchParams.get("benchmark_id");

	const params = new URLSearchParams();
	if (window) params.set("window", window);
	if (benchmarkId) params.set("benchmark_id", benchmarkId);

	const qs = params.toString();
	redirect(302, `/analytics/${entityId}${qs ? `?${qs}` : ""}`);
};
