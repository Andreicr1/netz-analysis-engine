/** Fund Detail Page — loads all fund data in parallel via SSR. */
import { createServerApiClient } from "$lib/api/client";

export const load = async ({ parent, params }: { parent: () => Promise<{ token: string }>; params: { cik: string } }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { cik } = params;

	const [detail, holdings, prospectus, peers, reverseHoldings, holdingsHistory, styleHistory] =
		await Promise.allSettled([
			api.get(`/sec/funds/${cik}`),
			api.get(`/sec/funds/${cik}/holdings`),
			api.get(`/sec/funds/${cik}/prospectus`),
			api.get(`/sec/funds/${cik}/peer-analysis`),
			api.get(`/sec/funds/${cik}/reverse-holdings`),
			api.get(`/sec/funds/${cik}/holdings-history`),
			api.get(`/sec/funds/${cik}/style-history?limit=8`),
		]);

	return {
		cik,
		detail: detail.status === "fulfilled" ? detail.value : null,
		holdings: holdings.status === "fulfilled" ? holdings.value : null,
		prospectus: prospectus.status === "fulfilled" ? prospectus.value : null,
		peers: peers.status === "fulfilled" ? peers.value : null,
		reverseHoldings: reverseHoldings.status === "fulfilled" ? reverseHoldings.value : null,
		holdingsHistory: holdingsHistory.status === "fulfilled" ? holdingsHistory.value : null,
		styleHistory: styleHistory.status === "fulfilled" ? styleHistory.value : null,
	};
};
