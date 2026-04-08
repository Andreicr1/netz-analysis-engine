/**
 * Wealth Library landing — server loader.
 *
 * Phase 3 of the Library frontend (spec §3.4 + §3.6). Loads the
 * top-level `LibraryTree` (L1 + L2 folders) so the shell can paint
 * the navigation pane immediately on first render. Returns a
 * `RouteData<LibraryTree>` per Stability Guardrails §3.2 — we never
 * `throw error()` from the loader so the page component can render
 * its own `PanelErrorState` / `PanelEmptyState` branches without
 * tripping the global SvelteKit error boundary.
 */

import type { PageServerLoad } from "./$types";
import { errData, okData, type RouteData } from "@investintell/ui/runtime";
import { createServerApiClient } from "$lib/api/client";
import type { LibraryTree } from "$lib/types/library";

const TREE_TIMEOUT_MS = 8000;

interface LibraryLoadResult {
	tree: RouteData<LibraryTree>;
	initialPath: string | null;
}

export const load: PageServerLoad = async ({
	parent,
}): Promise<LibraryLoadResult> => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	try {
		const tree = await api.get<LibraryTree>(
			"/library/tree",
			undefined,
			{ signal: AbortSignal.timeout(TREE_TIMEOUT_MS) },
		);
		return { tree: okData(tree), initialPath: null };
	} catch (err: unknown) {
		if (err instanceof DOMException && err.name === "TimeoutError") {
			return {
				tree: errData(
					"TIMEOUT",
					`Loading the Library took longer than ${TREE_TIMEOUT_MS / 1000}s. Please try again.`,
					true,
				),
				initialPath: null,
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
					initialPath: null,
				};
			}
			return {
				tree: errData(
					`HTTP_${status}`,
					"The Library service returned an error. Please try again in a moment.",
					true,
				),
				initialPath: null,
			};
		}
		console.error("library_tree_load_unknown_error", err);
		return {
			tree: errData(
				"UNKNOWN",
				err instanceof Error ? err.message : "Failed to load the Library.",
				true,
			),
			initialPath: null,
		};
	}
};
