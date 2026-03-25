/** Fund fact sheet — SSR: load fund detail + style history. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { FundDetailResponse, StyleHistoryResponse } from "$lib/types/sec-funds";
import { EMPTY_STYLE_HISTORY } from "$lib/types/sec-funds";

export const load: PageServerLoad = async ({ params, parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { crd, cik } = params;

	const [fund, styleHistory] = await Promise.all([
		api.get<FundDetailResponse>(`/sec/funds/${cik}`).catch(() => null),
		api
			.get<StyleHistoryResponse>(`/sec/funds/${cik}/style-history`)
			.catch(() => EMPTY_STYLE_HISTORY),
	]);

	return { crd, cik, fund, styleHistory };
};
