/**
 * X3.1 Builder Workspace — unified loader.
 *
 * Merges the former /allocation/[profile] strategic loader with
 * /portfolio/builder's portfolio list so a single server load
 * hydrates all three tabs (STRATEGIC / PORTFOLIO / STRESS).
 *
 * Uses the RouteData<T> contract for the strategic branch (§3.2
 * Stability Guardrails) — that is the only hard dependency. History,
 * proposal, regime, and portfolios each degrade gracefully to empty
 * / null on failure so a single upstream blip never blanks the page.
 *
 * Parallelism: every endpoint fires via Promise.all with per-request
 * timeouts so the slowest call caps the page TTFB, not their sum.
 */
import type { PageServerLoad } from "./$types";
import { okData, errData, type RouteData } from "@investintell/ui/runtime";
import { createServerApiClient } from "$wealth/api/client";
import {
	ALLOCATION_PROFILES,
	type AllocationProfile,
	type ApprovalHistoryResponse,
	type LatestProposalResponse,
	type StrategicAllocationResponse,
} from "$wealth/types/allocation-page";
import type { ModelPortfolio } from "$wealth/types/model-portfolio";

const FETCH_TIMEOUT_MS = 8000;

interface RegimeSnapshot {
	regime: string | null;
	stressScore: number | null;
}

interface GlobalRegimeRead {
	as_of_date: string;
	raw_regime: string | null;
	stress_score: number | null;
}

function isAllocationProfile(raw: string): raw is AllocationProfile {
	return (ALLOCATION_PROFILES as readonly string[]).includes(raw);
}

interface LoadResult {
	profile: AllocationProfile | null;
	strategic: RouteData<StrategicAllocationResponse>;
	history: ApprovalHistoryResponse;
	proposal: LatestProposalResponse | null;
	regime: RegimeSnapshot | null;
	portfolios: ModelPortfolio[];
	actorRole: string | null;
}

export const load: PageServerLoad = async ({
	params,
	parent,
}): Promise<LoadResult> => {
	const { token, actor } = await parent();
	const actorRole = actor?.role ?? null;

	const profileRaw = params.profile.toLowerCase();
	if (!token) {
		return {
			profile: null,
			strategic: errData("HTTP_401", "Not authenticated", true),
			history: emptyHistory(profileRaw),
			proposal: null,
			regime: null,
			portfolios: [],
			actorRole,
		};
	}
	if (!isAllocationProfile(profileRaw)) {
		return {
			profile: null,
			strategic: errData(
				"BAD_REQUEST",
				`Unknown allocation profile '${params.profile}'.`,
				false,
			),
			history: emptyHistory(profileRaw),
			proposal: null,
			regime: null,
			portfolios: [],
			actorRole,
		};
	}
	const profile: AllocationProfile = profileRaw;

	const api = createServerApiClient(token);

	const strategicPromise = (async (): Promise<
		RouteData<StrategicAllocationResponse>
	> => {
		try {
			const resp = await api.get<StrategicAllocationResponse>(
				`/portfolio/profiles/${profile}/strategic-allocation`,
				undefined,
				{ signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
			);
			return okData(resp);
		} catch (err: unknown) {
			if (err instanceof DOMException && err.name === "TimeoutError") {
				return errData(
					"TIMEOUT",
					"Loading the allocation took too long. Please retry.",
					true,
				);
			}
			if (err && typeof err === "object" && "status" in err) {
				const status = (err as { status: number }).status;
				return errData(
					`HTTP_${status}`,
					"The allocation service returned an error.",
					true,
				);
			}
			return errData(
				"UNKNOWN",
				err instanceof Error ? err.message : "Failed to load allocation.",
				true,
			);
		}
	})();

	const historyPromise = api
		.get<ApprovalHistoryResponse>(
			`/portfolio/profiles/${profile}/approval-history?limit=10&offset=0`,
			undefined,
			{ signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
		)
		.catch((): ApprovalHistoryResponse => emptyHistory(profile));

	const proposalPromise = api
		.get<LatestProposalResponse>(
			`/portfolio/profiles/${profile}/latest-proposal`,
			undefined,
			{ signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
		)
		.catch(() => null);

	const regimePromise = api
		.get<GlobalRegimeRead>("/macro/regime", undefined, {
			signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
		})
		.then((r): RegimeSnapshot | null => ({
			regime: r.raw_regime ?? null,
			stressScore:
				typeof r.stress_score === "number" ? r.stress_score : null,
		}))
		.catch(() => null);

	const portfoliosPromise = api
		.get<ModelPortfolio[]>("/model-portfolios", undefined, {
			signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
		})
		.catch((): ModelPortfolio[] => []);

	const [strategic, history, proposal, regime, portfolios] =
		await Promise.all([
			strategicPromise,
			historyPromise,
			proposalPromise,
			regimePromise,
			portfoliosPromise,
		]);

	return {
		profile,
		strategic,
		history,
		proposal,
		regime,
		portfolios,
		actorRole,
	};
};

function emptyHistory(profile: string): ApprovalHistoryResponse {
	return {
		organization_id: "00000000-0000-0000-0000-000000000000",
		profile,
		total: 0,
		entries: [],
	};
}
