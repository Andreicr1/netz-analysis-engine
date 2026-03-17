/** Document list — filterable, paginated. Includes root folders. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ params, parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const page = url.searchParams.get("page") ?? "1";
	const rootFolder = url.searchParams.get("root_folder");
	const domain = url.searchParams.get("domain");

	const [documents, rootFolders] = await Promise.allSettled([
		api.get("/documents", {
			page,
			page_size: 50,
			...(rootFolder ? { root_folder: rootFolder } : {}),
			...(domain ? { domain } : {}),
		}),
		api.get("/documents/root-folders"),
	]);

	return {
		documents: documents.status === "fulfilled" ? documents.value : { items: [], total: 0 },
		rootFolders: rootFolders.status === "fulfilled" ? rootFolders.value : [],
		fundId: params.fundId,
	};
};
