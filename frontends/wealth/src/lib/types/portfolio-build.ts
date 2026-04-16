// PR-A5 Section A.2 — types for POST /api/v1/portfolios/{id}/build (Job-or-Stream).
// Kept DISTINCT from ConstructRunEvent (legacy /model-portfolios/{id}/construct path)
// until the legacy wiring is fully retired in PR-A7.

export interface BuildAccepted {
	job_id: string;
	stream_url: string; // "/api/v1/jobs/{job_id}/stream"
	status: "accepted";
}

export type BuildPhase =
	| "STARTED"
	| "FACTOR_MODELING"
	| "SHRINKAGE"
	| "SOCP_OPTIMIZATION"
	| "BACKTESTING"
	| "COMPLETED"
	| "CANCELLED"
	| "ERROR"
	| "DEDUPED";

export interface BuildEvent {
	type: string; // humanised label from backend (already sanitised server-side)
	raw_type?: string; // original backend event type, e.g. "optimizer_phase_complete"
	phase?: BuildPhase | string; // pipeline phase OR optimizer cascade sub-phase
	message?: string;
	progress?: number; // 0.0 … 1.0
	metrics?: Record<string, unknown>;
	run_id?: string; // only populated on COMPLETED
	status?: string;
	reason?: string; // only on ERROR / CANCELLED / DEDUPED
	objective_value?: number | null; // only on optimizer_phase_complete
}
