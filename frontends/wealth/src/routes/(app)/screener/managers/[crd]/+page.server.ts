/** Manager Detail Page — loads basic manager info via SSR for title/SEO. */
import { createServerApiClient } from "$lib/api/client";

export const load = async ({
	parent,
	params,
}: {
	parent: () => Promise<{ token: string }>;
	params: { crd: string };
}) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { crd } = params;

	let firmName = `Manager ${crd}`;
	try {
		const profile = await api.get<{ firm_name: string }>(
			`/manager-screener/managers/${crd}/profile`,
		);
		if (profile?.firm_name) firmName = profile.firm_name;
	} catch {
		// Fallback to CRD as title — ManagerDetailPanel will fetch its own data
	}

	return { crd, firmName };
};
