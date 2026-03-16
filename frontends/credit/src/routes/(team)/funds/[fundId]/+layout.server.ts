/** Fund context layout — validates fundId belongs to org, loads fund metadata. */
import { error } from "@sveltejs/kit";
import type { LayoutServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

interface Fund {
	id: string;
	name: string;
	status: string;
	vertical: string;
	organization_id: string;
}

export const load: LayoutServerLoad = async ({ params, parent }) => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);

	// Validate fundId exists and belongs to current org
	let fund: Fund;
	try {
		fund = await api.get<Fund>(`/funds/${params.fundId}`);
	} catch (err) {
		if (err && typeof err === "object" && "status" in err) {
			const status = (err as { status: number }).status;
			if (status === 404) throw error(404, "Fund not found.");
			if (status === 403) throw error(403, "You don't have access to this fund.");
		}
		throw error(500, "Failed to load fund.");
	}

	// Extra safety: verify org_id matches
	if (fund.organization_id && fund.organization_id !== actor.organization_id) {
		throw error(403, "Fund does not belong to your organization.");
	}

	return { fund };
};
