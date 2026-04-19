/**
 * Portfolio Reports Store — report history, generation triggers, SSE job tracking.
 *
 * Lives in the portfolio detail context (portfolio/models/[portfolioId]).
 * Manages:
 *   1. Report history: GET /model-portfolios/{id}/reports
 *   2. Report generation: POST /model-portfolios/{id}/reports/generate → job_id
 *   3. SSE streaming: GET /model-portfolios/{id}/reports/stream/{job_id}
 *
 * SSE uses fetch() + ReadableStream (not EventSource — auth headers required).
 * No localStorage. All state is in-memory. Svelte 5 runes.
 */

import { createClientApiClient } from "$wealth/api/client";
import type {
	ReportGenerateRequest,
	ReportGenerateResponse,
	ReportHistoryItem,
	ReportHistoryResponse,
	ReportProgressEvent,
	ReportStage,
	ReportType,
} from "$wealth/types/model-portfolio";

// ── Types ───────────────────────────────────────────────────

export interface ActiveJob {
	jobId: string;
	reportType: ReportType;
	stage: ReportStage;
	message: string;
	pct: number;
	status: "running" | "completed" | "failed";
	error?: string;
}

export interface PortfolioReportsStore {
	// History
	readonly reports: ReportHistoryItem[];
	readonly reportsLoading: boolean;
	readonly reportsError: string | null;
	refreshReports: () => void;
	// Active Jobs
	readonly activeJobs: ActiveJob[];
	readonly hasActiveJobs: boolean;
	// Generation
	triggerGeneration: (req: ReportGenerateRequest) => Promise<string | null>;
	// Lifecycle
	destroy: () => void;
}

// ── Config ──────────────────────────────────────────────────

export interface ReportsStoreConfig {
	portfolioId: string;
	getToken: () => Promise<string>;
	/** Initial reports from SSR */
	initialReports?: ReportHistoryItem[];
}

// ── Store Factory ───────────────────────────────────────────

export function createPortfolioReportsStore(config: ReportsStoreConfig): PortfolioReportsStore {
	const { portfolioId, getToken, initialReports } = config;
	const api = createClientApiClient(getToken);

	// ── Report History State ────────────────────────────────
	let reports = $state<ReportHistoryItem[]>(initialReports ?? []);
	let reportsLoading = $state(false);
	let reportsError = $state<string | null>(null);

	async function fetchReports(): Promise<void> {
		if (reportsLoading) return;
		reportsLoading = true;
		reportsError = null;
		try {
			const resp = await api.get<ReportHistoryResponse>(
				`/model-portfolios/${portfolioId}/reports`,
			);
			reports = resp.reports ?? [];
		} catch (e) {
			reportsError = e instanceof Error ? e.message : "Failed to fetch reports";
		} finally {
			reportsLoading = false;
		}
	}

	// ── Active Jobs State ──────────────────────────────────
	let activeJobs = $state<ActiveJob[]>([]);
	const abortControllers: Map<string, AbortController> = new Map();

	function hasActiveJobs(): boolean {
		return activeJobs.some((j) => j.status === "running");
	}

	// ── SSE Stream Management ──────────────────────────────

	async function connectSSE(jobId: string, reportType: ReportType): Promise<void> {
		const controller = new AbortController();
		abortControllers.set(jobId, controller);

		try {
			const token = await getToken();
			const url = `/api/v1/model-portfolios/${portfolioId}/reports/stream/${jobId}`;
			const response = await fetch(url, {
				headers: { Authorization: `Bearer ${token}` },
				signal: controller.signal,
			});

			if (!response.ok || !response.body) {
				updateJob(jobId, { status: "failed", error: `Stream failed: ${response.status}` });
				return;
			}

			const reader = response.body.getReader();
			const decoder = new TextDecoder();
			let buffer = "";

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split("\n");
				buffer = lines.pop() ?? "";

				let currentEvent = "";
				let currentData = "";

				for (const line of lines) {
					if (line.startsWith("event:")) {
						currentEvent = line.slice(6).trim();
					} else if (line.startsWith("data:")) {
						currentData = line.slice(5).trim();
					} else if (line === "" && currentEvent && currentData) {
						handleSSEMessage(jobId, currentEvent, currentData);
						currentEvent = "";
						currentData = "";
					}
				}
			}
		} catch (e) {
			if (controller.signal.aborted) return; // Expected on destroy
			updateJob(jobId, {
				status: "failed",
				error: e instanceof Error ? e.message : "SSE connection lost",
			});
		} finally {
			abortControllers.delete(jobId);
		}
	}

	function handleSSEMessage(jobId: string, event: string, rawData: string): void {
		try {
			const data = JSON.parse(rawData);

			if (event === "progress") {
				const progress = data as ReportProgressEvent;
				updateJob(jobId, {
					stage: progress.stage,
					message: progress.message,
					pct: progress.pct,
				});
			} else if (event === "done") {
				updateJob(jobId, {
					stage: "COMPLETED",
					message: "Report completed",
					pct: 100,
					status: "completed",
				});
				// Refresh report list to include the new report
				fetchReports();
			} else if (event === "error") {
				updateJob(jobId, {
					status: "failed",
					error: data.error ?? "Generation failed",
				});
			}
		} catch {
			// Malformed SSE data — ignore
		}
	}

	function updateJob(jobId: string, patch: Partial<ActiveJob>): void {
		activeJobs = activeJobs.map((j) =>
			j.jobId === jobId ? { ...j, ...patch } : j,
		);
	}

	// ── Report Generation Trigger ───────���──────────────────

	async function triggerGeneration(req: ReportGenerateRequest): Promise<string | null> {
		try {
			const resp = await api.post<ReportGenerateResponse>(
				`/model-portfolios/${portfolioId}/reports/generate`,
				req,
			);

			const job: ActiveJob = {
				jobId: resp.job_id,
				reportType: req.report_type,
				stage: "QUEUED",
				message: "Report generation queued",
				pct: 0,
				status: "running",
			};

			activeJobs = [...activeJobs, job];

			// Connect to SSE stream in background
			connectSSE(resp.job_id, req.report_type);

			return resp.job_id;
		} catch (e) {
			reportsError = e instanceof Error ? e.message : "Failed to trigger report";
			return null;
		}
	}

	// ── Lifecycle ──────────────────────────────────────────

	function destroy(): void {
		for (const [, controller] of abortControllers) {
			controller.abort();
		}
		abortControllers.clear();
	}

	// ── Public API ─────────────────────────────────────────

	return {
		get reports() { return reports; },
		get reportsLoading() { return reportsLoading; },
		get reportsError() { return reportsError; },
		refreshReports: fetchReports,
		get activeJobs() { return activeJobs; },
		get hasActiveJobs() { return hasActiveJobs(); },
		triggerGeneration,
		destroy,
	};
}
