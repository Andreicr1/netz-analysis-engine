/**
 * FactSheet load — Stability Guardrails Phase 3 retrofit (§3.2 + §4.2 B2.1/B2.2).
 *
 * Returns a `RouteData<FactSheetPayload>` instead of calling `error()`.
 * The frontend renders the three branches explicitly:
 *   - `error` → <PanelErrorState> with optional retry
 *   - `data == null` → <PanelEmptyState>
 *   - success → <FundFactSheet> wrapped in <svelte:boundary>
 *
 * No `throw error()`, no black-screen failure mode (the §7.2 incident).
 *
 * The fetch is hard-capped at 8 s via `AbortSignal.timeout(8000)`. The
 * api client already retries idempotent GETs once on TimeoutError, so
 * the user-facing wall is effectively 16 s before we tip into a
 * recoverable error message.
 */

import type { PageServerLoad } from './$types';
import { okData, errData, type RouteData } from '@investintell/ui/runtime';
import { createServerApiClient } from '$lib/api/client';

const FACT_SHEET_TIMEOUT_MS = 8000;

// FactSheetPayload is intentionally typed as `unknown` at the load
// boundary — the page component does the runtime narrowing it needs.
// Tightening the contract is a follow-up that lives with the screener
// schema generation, not the stability sprint.
export type FactSheetPayload = Record<string, unknown>;

interface FactSheetLoadResult {
    factSheet: RouteData<FactSheetPayload>;
}

export const load: PageServerLoad = async ({
    params,
    parent,
}): Promise<FactSheetLoadResult> => {
    const { id } = params;
    const { token } = await parent();
    const api = createServerApiClient(token);

    try {
        const factSheet = await api.get<FactSheetPayload>(
            `/screener/catalog/${id}/fact-sheet`,
            undefined,
            { signal: AbortSignal.timeout(FACT_SHEET_TIMEOUT_MS) },
        );
        return { factSheet: okData(factSheet) };
    } catch (err: unknown) {
        // Timeout / network — recoverable: the user can hit "Try
        // again" once the upstream warms back up.
        if (err instanceof DOMException && err.name === 'TimeoutError') {
            return {
                factSheet: errData(
                    'TIMEOUT',
                    `Loading the fund took longer than ${FACT_SHEET_TIMEOUT_MS / 1000}s. The upstream may be slow — please try again.`,
                    true,
                ),
            };
        }
        // HTTP errors lifted by the api client carry a numeric `status`.
        if (err && typeof err === 'object' && 'status' in err) {
            const status = (err as { status: number }).status;
            if (status === 404) {
                return {
                    factSheet: errData(
                        'NOT_FOUND',
                        'This fund is no longer in the catalog. It may have been removed or merged.',
                        false,
                    ),
                };
            }
            if (status === 401 || status === 403) {
                return {
                    factSheet: errData(
                        `HTTP_${status}`,
                        'You do not have permission to view this fund. Re-authenticating may help.',
                        true,
                    ),
                };
            }
            return {
                factSheet: errData(
                    `HTTP_${status}`,
                    'The fact sheet service returned an error. Please try again in a moment.',
                    true,
                ),
            };
        }
        // Unknown failure — surface a generic recoverable message but
        // log the underlying error so server logs still tell the story.
        console.error('factsheet_load_unknown_error', { id, err });
        return {
            factSheet: errData(
                'UNKNOWN',
                err instanceof Error ? err.message : 'Failed to load fund data.',
                true,
            ),
        };
    }
};
