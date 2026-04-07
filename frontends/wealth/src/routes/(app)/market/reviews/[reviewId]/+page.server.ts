/**
 * Macro Review Detail load — Stability Guardrails Route Data Contract (§3.2).
 *
 * Loads a single committee review by ID. Returns `review` as a
 * `RouteData<MacroReview>` so the page component branches explicitly
 * on error / empty / data rather than falling into the SvelteKit
 * default error boundary. Fetch is hard-capped at 8 s.
 */

import type { PageServerLoad } from "./$types";
import { okData, errData, type RouteData } from "@investintell/ui/runtime";
import { createServerApiClient } from "$lib/api/client";
import type { MacroReview } from "$lib/types/macro";

const REVIEW_TIMEOUT_MS = 8000;

interface ReviewLoadResult {
	review: RouteData<MacroReview>;
}

export const load: PageServerLoad = async ({ parent, params }): Promise<ReviewLoadResult> => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	try {
		const reviews = await api.get<MacroReview[]>(
			"/macro/reviews",
			{ limit: 50 },
			{ signal: AbortSignal.timeout(REVIEW_TIMEOUT_MS) },
		);
		const found = reviews.find((r) => r.id === params.reviewId);
		if (!found) {
			return {
				review: errData(
					"NOT_FOUND",
					"This committee review is not in the latest 50 entries. It may have been archived.",
					false,
				),
			};
		}
		return { review: okData(found) };
	} catch (err: unknown) {
		if (err instanceof DOMException && err.name === "TimeoutError") {
			return {
				review: errData(
					"TIMEOUT",
					`Loading the review took longer than ${REVIEW_TIMEOUT_MS / 1000}s. Please try again.`,
					true,
				),
			};
		}
		if (err && typeof err === "object" && "status" in err) {
			const status = (err as { status: number }).status;
			if (status === 401 || status === 403) {
				return {
					review: errData(
						`HTTP_${status}`,
						"You do not have permission to view this review.",
						true,
					),
				};
			}
			return {
				review: errData(
					`HTTP_${status}`,
					"The macro review service returned an error. Please try again in a moment.",
					true,
				),
			};
		}
		console.error("review_load_unknown_error", { reviewId: params.reviewId, err });
		return {
			review: errData(
				"UNKNOWN",
				err instanceof Error ? err.message : "Failed to load review.",
				true,
			),
		};
	}
};
