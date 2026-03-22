/** Document detail — single document metadata. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { WealthDocument } from "$lib/types/document";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const document = await api
		.get<WealthDocument>(`/wealth/documents/${params.documentId}`)
		.catch(() => null);

	return { document, documentId: params.documentId! };
};
