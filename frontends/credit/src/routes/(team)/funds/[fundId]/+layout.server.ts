/** Fund context layout — validates fundId belongs to org, loads fund metadata. */
import { errData } from "@investintell/ui/runtime";
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
			if (status === 404) {
				return { fund: null, fundRoute: errData("NOT_FOUND", "Fund not found.", false) };
			}
			if (status === 403) {
				return {
					fund: null,
					fundRoute: errData("FORBIDDEN", "You don't have access to this fund.", false),
				};
			}
		}
		return { fund: null, fundRoute: errData("HTTP_500", "Failed to load fund.", true) };
	}

	// Extra safety: verify org_id matches
	if (fund.organization_id && fund.organization_id !== actor.organization_id) {
		return {
			fund: null,
			fundRoute: errData("FORBIDDEN", "Fund does not belong to your organization.", false),
		};
	}

	return { fund };
};
