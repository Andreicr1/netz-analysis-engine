/** Allocation — standalone page for strategic/tactical/effective allocation management. */
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = async () => {
	// AllocationView is self-loading (fetches data client-side).
	// No server-side data needed.
	return {};
};
