/**
 * Wealth Library deep-link route — server loader.
 *
 * Phase 3 (spec §2.5 deep linking). The catch-all `[...path]`
 * captures everything below `/library/...`, hands the encoded path
 * to the page as `initialPath`, and reuses the same
 * `GET /library/tree` request as the landing page so refreshes on
 * a deep link still hydrate the navigation pane in one round trip.
 *
 * Returning `RouteData<LibraryTree>` keeps the contract identical
 * to `/library/+page.server.ts` so the same page component handles
 * both routes without forking the success/error branches.
 */

import type { PageServerLoad } from "./$types";
import { errData, okData, type RouteData } from "@investintell/ui/runtime";
import { createServerApiClient } from "$lib/api/client";
import type { LibraryTree } from "$lib/types/library";

const TREE_TIMEOUT_MS = 8000;

interface LibraryLoadResult {
	tree: RouteData<LibraryTree>;
	initialPath: string | null;
	actorRole: string | null;
}

export const load: PageServerLoad = async ({
	parent,
	params,
}): Promise<LibraryLoadResult> => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);
	const initialPath = params.path && params.path.length > 0 ? params.path : null;
	const actorRole = actor?.role ?? null;

	try {
		const tree = await api.get<LibraryTree>(
			"/library/tree",
			undefined,
			{ signal: AbortSignal.timeout(TREE_TIMEOUT_MS) },
		);
		return { tree: okData(tree), initialPath, actorRole };
	} catch (err: unknown) {
		if (err instanceof DOMException && err.name === "TimeoutError") {
			return {
				tree: errData(
					"TIMEOUT",
					`Loading the Library took longer than ${TREE_TIMEOUT_MS / 1000}s. Please try again.`,
					true,
				),
				initialPath,
				actorRole,
			};
		}
		if (err && typeof err === "object" && "status" in err) {
			const status = (err as { status: number }).status;
			if (status === 401 || status === 403) {
				return {
					tree: errData(
						`HTTP_${status}`,
						"You do not have permission to view the Library.",
						true,
					),
					initialPath,
					actorRole,
				};
			}
			return {
				tree: errData(
					`HTTP_${status}`,
					"The Library service returned an error. Please try again in a moment.",
					true,
				),
				initialPath,
				actorRole,
			};
		}
		console.error("library_tree_deeplink_load_unknown_error", err);
		return {
			tree: errData(
				"UNKNOWN",
				err instanceof Error ? err.message : "Failed to load the Library.",
				true,
			),
			initialPath,
			actorRole,
		};
	}
};
