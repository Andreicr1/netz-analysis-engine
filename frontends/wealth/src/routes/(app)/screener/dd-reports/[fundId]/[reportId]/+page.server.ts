/**
 * DD Report detail load — Stability Guardrails Route Data Contract (§3.2).
 *
 * Returns the full report plus actor context for approval. `report` is
 * a `RouteData<DDReportFull>` so the page component renders the three
 * explicit branches (error / empty / data) instead of falling into the
 * SvelteKit default error boundary. Fetch hard-capped at 8 s.
 */

import type { PageServerLoad } from "./$types";
import { okData, errData, type RouteData } from "@investintell/ui/runtime";
import { createServerApiClient } from "$lib/api/client";
import type { DDReportFull } from "$lib/types/dd-report";

const REPORT_TIMEOUT_MS = 8000;

interface DDReportLoadResult {
	report: RouteData<DDReportFull>;
	fundId: string;
	reportId: string;
	actorId: string | null;
	actorRole: string | null;
}

export const load: PageServerLoad = async ({ parent, params }): Promise<DDReportLoadResult> => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);
	const fundId = params.fundId!;
	const reportId = params.reportId!;
	const actorId = actor?.user_id ?? null;
	const actorRole = actor?.role ?? null;

	try {
		const report = await api.get<DDReportFull>(
			`/dd-reports/${reportId}`,
			undefined,
			{ signal: AbortSignal.timeout(REPORT_TIMEOUT_MS) },
		);
		return { report: okData(report), fundId, reportId, actorId, actorRole };
	} catch (err: unknown) {
		if (err instanceof DOMException && err.name === "TimeoutError") {
			return {
				report: errData(
					"TIMEOUT",
					`Loading the DD report took longer than ${REPORT_TIMEOUT_MS / 1000}s. Please try again.`,
					true,
				),
				fundId,
				reportId,
				actorId,
				actorRole,
			};
		}
		if (err && typeof err === "object" && "status" in err) {
			const status = (err as { status: number }).status;
			if (status === 404) {
				return {
					report: errData(
						"NOT_FOUND",
						"This DD report no longer exists. It may have been regenerated or archived.",
						false,
					),
					fundId,
					reportId,
					actorId,
					actorRole,
				};
			}
			if (status === 401 || status === 403) {
				return {
					report: errData(
						`HTTP_${status}`,
						"You do not have permission to view this DD report.",
						true,
					),
					fundId,
					reportId,
					actorId,
					actorRole,
				};
			}
			return {
				report: errData(
					`HTTP_${status}`,
					"The DD report service returned an error. Please try again in a moment.",
					true,
				),
				fundId,
				reportId,
				actorId,
				actorRole,
			};
		}
		console.error("dd_report_load_unknown_error", { fundId, reportId, err });
		return {
			report: errData(
				"UNKNOWN",
				err instanceof Error ? err.message : "Failed to load DD report.",
				true,
			),
			fundId,
			reportId,
			actorId,
			actorRole,
		};
	}
};
