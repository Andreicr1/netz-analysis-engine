/** Document detail — loads document metadata + version history. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import { error } from "@sveltejs/kit";

export const load: PageServerLoad = async ({ params, parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId, documentId } = params;

	const [document, versions] = await Promise.allSettled([
		api.get(`/documents/${documentId}`),
		api.get(`/documents/${documentId}/versions`),
	]);

	if (document.status === "rejected") {
		throw error(404, "Document not found.");
	}

	return {
		document: document.value as Record<string, unknown>,
		versions: versions.status === "fulfilled" ? versions.value : [],
		fundId,
		documentId,
	};
};
