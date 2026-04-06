/** Model Detail — no additional SSR needed; workspace state provides portfolio data. */
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = async () => {
	return {};
};
