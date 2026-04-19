<!--
  MonthlyReportPanel — SSE-driven monthly client report generation.
  Simpler than LongFormReportPanel (no per-chapter progress).
  Events: started → done (with pdf_storage_key) | error.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { StatusBadge, Button } from "@investintell/ui";
	import { createClientApiClient } from "$wealth/api/client";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	interface Props {
		portfolioId: string;
		portfolioName: string;
	}

	let { portfolioId, portfolioName }: Props = $props();

	// ── State ────────────────────────────────────────────────────────
	let jobId = $state<string | null>(null);
	let generating = $state(false);
	let streaming = $state(false);
	let reportDone = $state(false);
	let reportStatus = $state<string | null>(null);
	let hasPdf = $state(false);
	let error = $state<string | null>(null);
	let downloading = $state(false);
	let abortController: AbortController | null = null;

	// ── Generate report ──────────────────────────────────────────────
	async function generateReport() {
		abortController?.abort();

		generating = true;
		error = null;
		reportDone = false;
		hasPdf = false;
		reportStatus = null;

		try {
			const api = createClientApiClient(getToken);
			const res = await api.post<{ job_id: string; portfolio_id: string }>(
				`/reporting/model-portfolios/${portfolioId}/monthly-report`,
				{},
			);
			jobId = res.job_id;
			generating = false;
			streaming = true;
			streamProgress(res.job_id);
		} catch (e) {
			if (e instanceof Error && e.message.includes("429")) {
				error = "Too many concurrent reports. Please wait for ongoing reports to finish.";
			} else {
				error = e instanceof Error ? e.message : "Failed to start report generation";
			}
			generating = false;
		}
	}

	// ── SSE stream (fetch + ReadableStream) ──────────────────────────
	async function streamProgress(activeJobId: string) {
		abortController = new AbortController();

		try {
			const token = await getToken();
			const apiBase =
				import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
			const response = await fetch(
				`${apiBase}/reporting/model-portfolios/${portfolioId}/monthly-report/stream/${activeJobId}`,
				{
					headers: {
						Authorization: `Bearer ${token}`,
						Accept: "text/event-stream",
					},
					signal: abortController.signal,
				},
			);

			if (!response.ok || !response.body) {
				error = `Stream connection failed (${response.status})`;
				streaming = false;
				return;
			}

			const reader = response.body.getReader();
			const decoder = new TextDecoder();
			let buffer = "";
			let currentEventType = "message";
			let currentData = "";

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split("\n");
				buffer = lines.pop() ?? "";

				for (const line of lines) {
					if (line.startsWith("event:")) {
						currentEventType = line.slice(6).trim();
					} else if (line.startsWith("data:")) {
						const d = line.slice(5).trim();
						currentData += currentData ? `\n${d}` : d;
					} else if (line === "" || line.startsWith(":")) {
						if (currentData) {
							try {
								const data = JSON.parse(currentData);
								handleSSEEvent(currentEventType, data);
							} catch {
								// malformed JSON — skip
							}
						}
						currentEventType = "message";
						currentData = "";
					}
				}

				if (reportDone) break;
			}
		} catch (err: unknown) {
			if (err instanceof DOMException && err.name === "AbortError") return;
			if (!reportDone) {
				error = err instanceof Error ? err.message : "Stream connection lost";
			}
		} finally {
			streaming = false;
			abortController = null;
		}
	}

	function handleSSEEvent(eventType: string, data: Record<string, unknown>) {
		if (eventType === "started") return;

		if (eventType === "done") {
			reportDone = true;
			reportStatus = (data.status as string) ?? "completed";
			hasPdf = !!data.pdf_storage_key;
			return;
		}

		if (eventType === "error") {
			error = (data.error as string) ?? "Report generation failed";
			reportDone = true;
			reportStatus = "failed";
		}
	}

	// ── Download PDF ─────────────────────────────────────────────────
	async function downloadPdf() {
		if (!jobId) return;
		downloading = true;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(
				`/reporting/model-portfolios/${portfolioId}/monthly-report/${jobId}/pdf`,
			);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `monthly-report-${portfolioName.toLowerCase().replace(/\s+/g, "-")}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			error = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloading = false;
		}
	}
</script>

<div class="mr">
	{#if error}
		<div class="mr-error">
			{error}
			<button class="mr-error-dismiss" onclick={() => (error = null)}>dismiss</button>
		</div>
	{/if}

	{#if !streaming && !reportDone}
		<div class="mr-trigger">
			<p class="mr-desc">
				Generate a monthly client report with portfolio performance, holdings snapshot,
				allocation breakdown, and market commentary.
			</p>
			<Button size="sm" onclick={generateReport} disabled={generating || !portfolioId}>
				{generating ? "Starting\u2026" : "Generate Monthly Report"}
			</Button>
		</div>
	{/if}

	{#if streaming}
		<div class="mr-status">
			<span class="mr-spinner"></span>
			<span class="mr-status-text">Generating monthly report&hellip;</span>
		</div>
	{/if}

	{#if reportDone}
		<div class="mr-result">
			<div class="mr-result-header">
				<span class="mr-result-title">Monthly Report</span>
				<StatusBadge status={reportStatus ?? "completed"} />
			</div>
			<div class="mr-actions">
				{#if hasPdf}
					<Button size="sm" onclick={downloadPdf} disabled={downloading}>
						{downloading ? "Downloading\u2026" : "Download PDF"}
					</Button>
				{:else if reportStatus !== "failed"}
					<span class="mr-no-pdf">PDF generation is pending. Try again shortly.</span>
				{/if}
				<Button size="sm" variant="outline" onclick={generateReport}>
					Generate New Report
				</Button>
			</div>
		</div>
	{/if}
</div>

<style>
	.mr {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-md, 16px);
	}

	.mr-error {
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
		border-radius: var(--ii-radius-sm, 8px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.mr-error-dismiss {
		background: none;
		border: none;
		color: inherit;
		cursor: pointer;
		text-decoration: underline;
		font-size: var(--ii-text-label, 0.75rem);
		font-family: var(--ii-font-sans);
	}

	.mr-trigger {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--ii-space-inline-md, 16px);
	}

	.mr-desc {
		margin: 0;
		color: var(--ii-text-secondary);
		font-size: var(--ii-text-small, 0.8125rem);
		max-width: 520px;
	}

	.mr-status {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: color-mix(in srgb, var(--ii-brand-primary) 4%, transparent);
	}

	.mr-status-text {
		color: var(--ii-brand-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
	}

	.mr-spinner {
		display: inline-block;
		width: 14px;
		height: 14px;
		border: 2px solid var(--ii-border-subtle);
		border-top-color: var(--ii-brand-primary);
		border-radius: 50%;
		animation: mr-spin 0.8s linear infinite;
	}

	@keyframes mr-spin {
		to { transform: rotate(360deg); }
	}

	.mr-result {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		overflow: hidden;
	}

	.mr-result-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		background: var(--ii-surface-alt);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.mr-result-title {
		font-weight: 600;
		font-size: var(--ii-text-body, 0.9375rem);
		color: var(--ii-text-primary);
	}

	.mr-actions {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 8px);
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	.mr-no-pdf {
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}
</style>
