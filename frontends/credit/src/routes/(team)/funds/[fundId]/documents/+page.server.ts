/** Document list — filterable, paginated. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ params, parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const page = url.searchParams.get("page") ?? "1";
	const rootFolder = url.searchParams.get("root_folder");
	const domain = url.searchParams.get("domain");

	let documents = { items: [], total: 0 };
	try {
		documents = await api.get("/documents", {
			page,
			page_size: 50,
			...(rootFolder ? { root_folder: rootFolder } : {}),
			...(domain ? { domain } : {}),
		});
	} catch {
		// Empty state
	}

	return { documents, fundId: params.fundId };
};
