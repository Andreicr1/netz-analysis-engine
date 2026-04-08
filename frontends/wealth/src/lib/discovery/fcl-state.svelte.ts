/**
 * URL-derived FCL state for the Discovery page.
 *
 * All discovery state lives in `page.url.searchParams` — no localStorage,
 * no sessionStorage, no module-level stores. Reactivity comes from Svelte 5's
 * `$app/state` `page` rune + `$derived`.
 */
import { page } from "$app/state";
import { goto } from "$app/navigation";
import type { FCLState } from "@investintell/ui";

export interface DiscoveryUrlState {
	readonly managerId: string | null;
	readonly fundId: string | null;
	readonly view: "dd" | "factsheet";
	readonly state: FCLState;
	selectManager: (id: string) => Promise<void>;
	selectFund: (id: string, view?: "dd" | "factsheet") => Promise<void>;
	changeView: (view: "dd" | "factsheet") => Promise<void>;
	closeCol3: () => Promise<void>;
	clearManager: () => Promise<void>;
	openAnalysis: (
		fundId: string,
		group?: "returns-risk" | "holdings" | "peer",
	) => Promise<void>;
}

export function useDiscoveryUrlState(): DiscoveryUrlState {
	const managerId = $derived(page.url.searchParams.get("manager"));
	const fundId = $derived(page.url.searchParams.get("fund"));
	const view = $derived(
		(page.url.searchParams.get("view") ?? "factsheet") as "dd" | "factsheet",
	);
	const state = $derived<FCLState>(
		fundId ? "expand-3" : managerId ? "expand-2" : "expand-1",
	);

	async function patch(updates: Record<string, string | null>): Promise<void> {
		const url = new URL(page.url);
		for (const [k, v] of Object.entries(updates)) {
			if (v === null) url.searchParams.delete(k);
			else url.searchParams.set(k, v);
		}
		await goto(url, { replaceState: true, noScroll: true, keepFocus: true });
	}

	return {
		get managerId() {
			return managerId;
		},
		get fundId() {
			return fundId;
		},
		get view() {
			return view;
		},
		get state() {
			return state;
		},
		selectManager: (id: string) =>
			patch({ manager: id, fund: null, view: null }),
		selectFund: (id: string, v: "dd" | "factsheet" = "factsheet") =>
			patch({ fund: id, view: v }),
		changeView: (v: "dd" | "factsheet") => patch({ view: v }),
		closeCol3: () => patch({ fund: null, view: null }),
		clearManager: () => patch({ manager: null, fund: null, view: null }),
		/** Navigates to the standalone full-width Analysis page. */
		openAnalysis: async (
			fundId: string,
			group: "returns-risk" | "holdings" | "peer" = "returns-risk",
		) => {
			await goto(
				`/discovery/funds/${encodeURIComponent(fundId)}/analysis?group=${group}`,
				{ noScroll: true },
			);
		},
	};
}
