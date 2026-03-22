/** Documents — list with domain filter. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { DocumentPage } from "$lib/types/document";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const params: Record<string, string> = { limit: "100" };
	const domain = url.searchParams.get("domain");
	if (domain) params.domain = domain;

	const documents = await api
		.get<DocumentPage>("/wealth/documents", params)
		.catch(() => ({ items: [], limit: 100, offset: 0 }) as DocumentPage);

	return { documents };
};
