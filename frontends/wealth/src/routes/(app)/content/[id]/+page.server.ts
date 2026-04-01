/** Content detail — full content with markdown body + approval context. */
import { error } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ContentFull } from "$lib/types/content";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);

	const content = await api.get<ContentFull>(`/content/${params.id}`).catch(() => null);
	if (!content) throw error(404, "Content not found");

	return {
		content,
		actorId: actor?.user_id ?? null,
		actorRole: actor?.role ?? null,
	};
};
