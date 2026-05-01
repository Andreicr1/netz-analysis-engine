/**
 * PR-BE-2 — defensive client-side profile filter for the
 * `/allocation/[profile]` loader's `/model-portfolios` fetch.
 *
 * The backend enforces the filter via `?profile={profile}` (so the
 * happy path is one round trip with the right rows), but the loader
 * also applies a belt-and-suspenders filter on the response so a
 * stale Cloudflare cache or a backend regression can never blank the
 * Builder workspace with a portfolio from the wrong profile (§6.2.2
 * `PortfolioTabContent`).
 *
 * This test pins the post-fetch unwrap + filter contract.
 */
import { describe, expect, it } from "vitest";

import type {
	ModelPortfolio,
	ModelPortfolioListResponse,
} from "../model-portfolio";

function makePortfolio(
	id: string,
	profile: string,
	displayName: string,
): ModelPortfolio {
	return {
		id,
		profile,
		display_name: displayName,
		description: null,
		benchmark_composite: null,
		inception_date: null,
		backtest_start_date: null,
		inception_nav: 100,
		status: "draft",
		state: "draft",
		state_metadata: {},
		state_changed_at: null,
		state_changed_by: null,
		allowed_actions: [],
		fund_selection_schema: null,
		created_at: "2026-04-30T12:00:00Z",
		created_by: null,
	};
}

/**
 * Mirrors the loader transform in
 * `frontends/terminal/src/routes/allocation/[profile]/+page.server.ts`.
 * Kept inline so the test exercises the exact contract without
 * import-cycling through SvelteKit's $app/env layer.
 */
function unwrapAndFilter(
	resp: ModelPortfolioListResponse,
	currentProfile: string,
): ModelPortfolio[] {
	return (resp.items ?? []).filter((p) => p.profile === currentProfile);
}

describe("model-portfolio list loader filter (PR-BE-2)", () => {
	it("returns only the current-profile rows", () => {
		const resp: ModelPortfolioListResponse = {
			items: [
				makePortfolio("a", "moderate", "Mod-1"),
				makePortfolio("b", "growth", "Gro-1"),
				makePortfolio("c", "moderate", "Mod-2"),
				makePortfolio("d", "conservative", "Con-1"),
			],
			next_cursor: null,
		};

		const result = unwrapAndFilter(resp, "moderate");

		expect(result.map((p) => p.id)).toEqual(["a", "c"]);
		expect(result.every((p) => p.profile === "moderate")).toBe(true);
	});

	it("returns [] when the response is empty", () => {
		const resp: ModelPortfolioListResponse = {
			items: [],
			next_cursor: null,
		};
		expect(unwrapAndFilter(resp, "growth")).toEqual([]);
	});

	it("never leaks a wrong-profile row even if backend regresses", () => {
		// Simulates a buggy backend that returned mixed profiles
		// despite ?profile=growth in the request.
		const resp: ModelPortfolioListResponse = {
			items: [
				makePortfolio("x", "growth", "G"),
				makePortfolio("y", "moderate", "Mod-leak"),
			],
			next_cursor: null,
		};

		const result = unwrapAndFilter(resp, "growth");

		expect(result).toHaveLength(1);
		expect(result[0]?.id).toBe("x");
	});

	it("tolerates a missing items field without throwing", () => {
		const resp = { next_cursor: null } as unknown as ModelPortfolioListResponse;
		expect(unwrapAndFilter(resp, "growth")).toEqual([]);
	});
});
