/**
 * Content detail load — Stability Guardrails Route Data Contract (§3.2).
 *
 * Returns `content` as a `RouteData<ContentFull>` so the page component
 * renders the three explicit branches (error / empty / data) instead of
 * falling into the SvelteKit default error boundary (the §7.2 black
 * screen failure mode). Fetch is hard-capped at 8 s via
 * `AbortSignal.timeout(8000)` per §3.2 R3.2.5.
 */

import type { PageServerLoad } from "./$types";
import { okData, errData, type RouteData } from "@investintell/ui/runtime";
import { createServerApiClient } from "$lib/api/client";
import type { ContentFull } from "$lib/types/content";

const CONTENT_TIMEOUT_MS = 8000;

interface ContentLoadResult {
	content: RouteData<ContentFull>;
	actorId: string | null;
	actorRole: string | null;
}

export const load: PageServerLoad = async ({ parent, params }): Promise<ContentLoadResult> => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);
	const actorId = actor?.user_id ?? null;
	const actorRole = actor?.role ?? null;

	try {
		const content = await api.get<ContentFull>(
			`/content/${params.id}`,
			undefined,
			{ signal: AbortSignal.timeout(CONTENT_TIMEOUT_MS) },
		);
		return { content: okData(content), actorId, actorRole };
	} catch (err: unknown) {
		if (err instanceof DOMException && err.name === "TimeoutError") {
			return {
				content: errData(
					"TIMEOUT",
					`Loading the content took longer than ${CONTENT_TIMEOUT_MS / 1000}s. The upstream may be slow — please try again.`,
					true,
				),
				actorId,
				actorRole,
			};
		}
		if (err && typeof err === "object" && "status" in err) {
			const status = (err as { status: number }).status;
			if (status === 404) {
				return {
					content: errData(
						"NOT_FOUND",
						"This content has been removed or never existed.",
						false,
					),
					actorId,
					actorRole,
				};
			}
			if (status === 401 || status === 403) {
				return {
					content: errData(
						`HTTP_${status}`,
						"You do not have permission to view this content.",
						true,
					),
					actorId,
					actorRole,
				};
			}
			return {
				content: errData(
					`HTTP_${status}`,
					"The content service returned an error. Please try again in a moment.",
					true,
				),
				actorId,
				actorRole,
			};
		}
		console.error("content_load_unknown_error", { id: params.id, err });
		return {
			content: errData(
				"UNKNOWN",
				err instanceof Error ? err.message : "Failed to load content.",
				true,
			),
			actorId,
			actorRole,
		};
	}
};
