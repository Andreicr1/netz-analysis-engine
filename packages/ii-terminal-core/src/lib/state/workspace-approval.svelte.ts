/**
 * workspace-approval — extracted approval gate state for the Builder.
 *
 * Reads the strategic allocation endpoint to determine whether the
 * current profile has an active approval. The Builder's RunControls
 * gate on this before allowing ``runBuildJob``.
 *
 * Plain class with ``$state`` fields — not a store.
 */

import type { AllocationProfile } from "../types/allocation-page";

export type ApprovalStatus =
	| "loading"
	| "approved"
	| "pending_approval"
	| "never_proposed"
	| "error";

export interface ApprovalState {
	status: ApprovalStatus;
	profile: AllocationProfile | null;
	last_approved_at: string | null;
	last_approved_by: string | null;
	error: string | null;
}

const INITIAL_STATE: ApprovalState = {
	status: "loading",
	profile: null,
	last_approved_at: null,
	last_approved_by: null,
	error: null,
};

class WorkspaceApproval {
	state = $state<ApprovalState>({ ...INITIAL_STATE });

	private _fetchId = 0;
	private _abort: AbortController | null = null;
	private _getToken: (() => Promise<string>) | null = null;

	setGetToken(fn: () => Promise<string>) {
		this._getToken = fn;
	}

	async refresh(profile: AllocationProfile): Promise<void> {
		this._abort?.abort();
		const abort = new AbortController();
		this._abort = abort;

		const fetchId = ++this._fetchId;

		this.state = { ...INITIAL_STATE, profile, status: "loading" };

		try {
			const token = await this._getToken?.();
			const base =
				(import.meta.env.VITE_API_BASE_URL as string | undefined) ??
				"http://localhost:8000/api/v1";

			const res = await fetch(
				`${base}/portfolio/profiles/${profile}/strategic-allocation`,
				{
					headers: {
						Authorization: `Bearer ${token}`,
						Accept: "application/json",
					},
					signal: abort.signal,
				},
			);

			if (fetchId !== this._fetchId) return;

			if (res.status === 404) {
				this.state = {
					status: "never_proposed",
					profile,
					last_approved_at: null,
					last_approved_by: null,
					error: null,
				};
				return;
			}

			if (!res.ok) {
				this.state = {
					status: "error",
					profile,
					last_approved_at: null,
					last_approved_by: null,
					error: `HTTP ${res.status}`,
				};
				return;
			}

			const data = await res.json();

			if (fetchId !== this._fetchId) return;

			this.state = {
				status: data.has_active_approval ? "approved" : "pending_approval",
				profile,
				last_approved_at: data.last_approved_at ?? null,
				last_approved_by: data.last_approved_by ?? null,
				error: null,
			};
		} catch (err: unknown) {
			if (abort.signal.aborted) return;
			if (fetchId !== this._fetchId) return;
			this.state = {
				status: "error",
				profile,
				last_approved_at: null,
				last_approved_by: null,
				error: err instanceof Error ? err.message : "Unknown error",
			};
		}
	}

	get canBuild(): boolean {
		return this.state.status === "approved";
	}
}

export const approval = new WorkspaceApproval();
