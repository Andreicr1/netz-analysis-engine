/** Document detail — loads document metadata + version history + event timeline. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import { errData } from "@investintell/ui/runtime";

export const load: PageServerLoad = async ({ params, parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId, documentId } = params;

	const [document, versions, timeline] = await Promise.allSettled([
		api.get(`/documents/${documentId}`),
		api.get(`/documents/${documentId}/versions`),
		api.get(`/funds/${fundId}/documents/${documentId}/timeline`),
	]);

	if (document.status === "rejected") {
		return {
			document: {},
			versions: [],
			timeline: [],
			fundId,
			documentId,
			documentRoute: errData("NOT_FOUND", "Document not found.", false),
		};
	}

	return {
		document: document.value as Record<string, unknown>,
		versions: versions.status === "fulfilled" ? versions.value : [],
		timeline: timeline.status === "fulfilled" ? (timeline.value as Array<Record<string, unknown>>) : [],
		fundId,
		documentId,
	};
};
