import type { PageServerLoad } from "./$types";
import { okData, errData, type RouteData } from "@investintell/ui/runtime";
import { createServerApiClient } from "@investintell/ii-terminal-core/api/client";
import type {
	SingleFundResearchResponse,
	ResearchScatterResponse,
} from "@investintell/ii-terminal-core/types/research";

const FETCH_TIMEOUT_MS = 8000;

interface LoadResult {
	research: RouteData<SingleFundResearchResponse>;
	scatter: RouteData<ResearchScatterResponse>;
}

export const load: PageServerLoad = async ({
	params,
	parent,
}): Promise<LoadResult> => {
	const { token } = await parent();
	if (!token) {
		return {
			research: errData("HTTP_401", "Not authenticated", true),
			scatter: errData("HTTP_401", "Not authenticated", true),
		};
	}

	const api = createServerApiClient(token);

	const researchPromise = (async (): Promise<
		RouteData<SingleFundResearchResponse>
	> => {
		try {
			const r = await api.get<SingleFundResearchResponse>(
				`/research/funds/${params.instrumentId}`,
				undefined,
				{ signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
			);
			return okData(r);
		} catch (err: unknown) {
			if (err instanceof DOMException && err.name === "TimeoutError") {
				return errData(
					"TIMEOUT",
					"Loading research data took too long. Please retry.",
					true,
				);
			}
			if (err && typeof err === "object" && "status" in err) {
				const status = (err as { status: number }).status;
				if (status === 404) {
					return errData(
						"NOT_FOUND",
						"No factor exposure data available for this fund.",
						false,
					);
				}
				return errData(
					`HTTP_${status}`,
					"The research service returned an error.",
					true,
				);
			}
			return errData(
				"UNKNOWN",
				err instanceof Error
					? err.message
					: "Failed to load research data.",
				true,
			);
		}
	})();

	const scatterPromise = api
		.get<ResearchScatterResponse>(
			"/research/scatter",
			undefined,
			{ signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
		)
		.then(okData)
		.catch(
			(): RouteData<ResearchScatterResponse> =>
				errData("UNKNOWN", "Scatter data unavailable.", true),
		);

	const [research, scatter] = await Promise.all([
		researchPromise,
		scatterPromise,
	]);

	return { research, scatter };
};
