import type {
	ModelPortfolio,
	ModelPortfolioListResponse,
} from "../types/model-portfolio";

type QueryValue = string | number | boolean | undefined;
type QueryParams = Record<string, QueryValue>;

interface ModelPortfolioApiClient {
	get(
		path: string,
		params?: QueryParams,
		options?: { signal?: AbortSignal },
	): Promise<ModelPortfolioListResponse>;
}

type RequestOptions = { signal?: AbortSignal };
type RequestOptionsFactory = () => RequestOptions;

export async function fetchAllModelPortfolios(
	api: ModelPortfolioApiClient,
	params: QueryParams = {},
	options?: RequestOptions | RequestOptionsFactory,
): Promise<ModelPortfolio[]> {
	const { cursor: initialCursor, ...baseParams } = params;
	const limit = baseParams.limit ?? 200;
	const items: ModelPortfolio[] = [];
	let cursor = typeof initialCursor === "string" ? initialCursor : undefined;
	const seenCursors = new Set<string>();
	if (cursor) seenCursors.add(cursor);

	for (;;) {
		const requestOptions = typeof options === "function" ? options() : options;
		const page = await api.get(
			"/model-portfolios",
			cursor
				? { ...baseParams, limit, cursor }
				: { ...baseParams, limit },
			requestOptions,
		);

		items.push(...(page.items ?? []));

		const nextCursor = page.next_cursor ?? null;
		if (!nextCursor) return items;
		if (seenCursors.has(nextCursor)) {
			throw new Error("Repeated next_cursor while loading model portfolios");
		}
		seenCursors.add(nextCursor);
		cursor = nextCursor;
	}
}
