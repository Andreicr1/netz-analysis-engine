/** Manager detail — SSR: load manager info + registered + private funds. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { SecManagerDetail } from "$lib/types/sec-analysis";
import type {
	RegisteredFundListResponse,
	PrivateFundListResponse,
} from "$lib/types/sec-funds";
import { EMPTY_REGISTERED_FUNDS, EMPTY_PRIVATE_FUNDS } from "$lib/types/sec-funds";

export const load: PageServerLoad = async ({ params, parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { crd } = params;

	const [manager, registeredFunds, privateFunds] = await Promise.all([
		api.get<SecManagerDetail>(`/sec/managers/${crd}`).catch(() => null),
		api
			.get<RegisteredFundListResponse>(`/sec/managers/${crd}/registered-funds`)
			.catch(() => EMPTY_REGISTERED_FUNDS),
		api
			.get<PrivateFundListResponse>(`/sec/managers/${crd}/private-funds`)
			.catch(() => EMPTY_PRIVATE_FUNDS),
	]);

	return { crd, manager, registeredFunds, privateFunds };
};
