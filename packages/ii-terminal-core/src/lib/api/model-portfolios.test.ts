import { describe, expect, test, vi } from "vitest";

import { fetchAllModelPortfolios } from "./model-portfolios";
import type {
	ModelPortfolio,
	ModelPortfolioListResponse,
} from "../types/model-portfolio";

type GetModelPortfolioPage = (
	path: string,
	params?: Record<string, string | number | boolean | undefined>,
	options?: { signal?: AbortSignal },
) => Promise<ModelPortfolioListResponse>;

function makePortfolio(id: string, profile = "growth"): ModelPortfolio {
	return {
		id,
		profile,
		display_name: `Portfolio ${id}`,
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

describe("fetchAllModelPortfolios", () => {
	test("follows next_cursor until the final page", async () => {
		const get = vi
			.fn<GetModelPortfolioPage>()
			.mockResolvedValueOnce({
				items: [makePortfolio("newest"), makePortfolio("middle")],
				next_cursor: "cursor-2",
			})
			.mockResolvedValueOnce({
				items: [makePortfolio("oldest")],
				next_cursor: null,
			});

		const result = await fetchAllModelPortfolios({ get }, { limit: 200 });

		expect(result.map((p) => p.id)).toEqual(["newest", "middle", "oldest"]);
		expect(get).toHaveBeenCalledTimes(2);
		expect(get).toHaveBeenNthCalledWith(1, "/model-portfolios", { limit: 200 }, undefined);
		expect(get).toHaveBeenNthCalledWith(
			2,
			"/model-portfolios",
			{ limit: 200, cursor: "cursor-2" },
			undefined,
		);
	});

	test("preserves caller query params on each page", async () => {
		const get = vi
			.fn<GetModelPortfolioPage>()
			.mockResolvedValueOnce({
				items: [makePortfolio("a", "moderate")],
				next_cursor: "cursor-2",
			})
			.mockResolvedValueOnce({
				items: [makePortfolio("b", "moderate")],
				next_cursor: null,
			});

		await fetchAllModelPortfolios({ get }, { profile: "moderate", limit: 100 });

		expect(get).toHaveBeenNthCalledWith(
			1,
			"/model-portfolios",
			{ profile: "moderate", limit: 100 },
			undefined,
		);
		expect(get).toHaveBeenNthCalledWith(
			2,
			"/model-portfolios",
			{ profile: "moderate", limit: 100, cursor: "cursor-2" },
			undefined,
		);
	});
});
