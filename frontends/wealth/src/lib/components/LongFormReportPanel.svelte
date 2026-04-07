<!--
  LongFormReportPanel — SSE-driven 8-chapter long-form DD report generation.
  Uses fetch() + ReadableStream (not EventSource — auth headers required).
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { StatusBadge, Button, formatPercent } from "@investintell/ui";
	import { Spinner } from "@investintell/ui/components/ui/spinner";
	import { createClientApiClient } from "$lib/api/client";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	interface Props {
		portfolioId: string;
		portfolioName: string;
	}

	let { portfolioId, portfolioName }: Props = $props();

	// ── Chapter registry (mirrors backend CHAPTER_REGISTRY) ──────────
	const CHAPTERS = [
		{ tag: "macro_context", order: 1, title: "Macro Context" },
		{ tag: "strategic_allocation", order: 2, title: "Strategic Allocation Rationale" },
		{ tag: "portfolio_composition", order: 3, title: "Portfolio Composition & Changes" },
		{ tag: "performance_attribution", order: 4, title: "Performance Attribution" },
		{ tag: "risk_decomposition", order: 5, title: "Risk Decomposition" },
		{ tag: "fee_analysis", order: 6, title: "Fee Analysis" },
		{ tag: "per_fund_highlights", order: 7, title: "Per-Fund Highlights" },
		{ tag: "forward_outlook", order: 8, title: "Forward Outlook" },
	] as const;

	type ChapterStatus = "pending" | "generating" | "completed" | "partial" | "failed";

	interface ChapterState {
		tag: string;
		order: number;
		title: string;
		status: ChapterStatus;
		confidence: number | null;
	}

	// ── State ────────────────────────────────────────────────────────
	let jobId = $state<string | null>(null);
	let generating = $state(false);
	let streaming = $state(false);
	let chapters = $state<ChapterState[]>([]);
	let reportDone = $state(false);
	let reportStatus = $state<string | null>(null);
	let hasPdf = $state(false);
	let error = $state<string | null>(null);
	let downloading = $state(false);
	let abortController: AbortController | null = null;

	let completedCount = $derived(
		chapters.filter((c) => c.status === "completed" || c.status === "partial").length,
	);

	// ── Generate report ──────────────────────────────────────────────
	async function generateReport() {
		// Abort any previous stream
		abortController?.abort();

		generating = true;
		error = null;
		reportDone = false;
		hasPdf = false;
		reportStatus = null;
		chapters = CHAPTERS.map((c) => ({
			...c,
			status: "pending" as ChapterStatus,
			confidence: null,
		}));

		try {
			const api = createClientApiClient(getToken);
			const res = await api.post<{ job_id: string; portfolio_id: string }>(
				`/reporting/model-portfolios/${portfolioId}/long-form-report`,
				{},
			);
			jobId = res.job_id;
			generating = false;
			streaming = true;
			streamProgress(res.job_id);
		} catch (e) {
			if (e instanceof Error && e.message.includes("429")) {
				error =
					"Too many concurrent reports being generated. Please wait for ongoing reports to finish.";
			} else {
				error = e instanceof Error ? e.message : "Failed to start report generation";
			}
			generating = false;
		}
	}

	// ── SSE stream (fetch + ReadableStream) ──────────────────────────
	async function streamProgress(activeJobId: string) {
		abortController = new AbortController();

		// Mark first chapter as generating
		if (chapters.length > 0) {
			chapters[0]!.status = "generating";
		}

		try {
			const token = await getToken();
			const apiBase =
				import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
			const response = await fetch(
				`${apiBase}/reporting/model-portfolios/${portfolioId}/long-form-report/stream/${activeJobId}`,
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
						// Empty line = end of event frame, `:` = comment (heartbeat)
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
		if (eventType === "started") {
			return;
		}

		if (eventType === "chapter_complete") {
			const tag = data.chapter as string;
			const status = data.status as string;
			const confidence = (data.confidence as number) ?? null;

			const idx = chapters.findIndex((c) => c.tag === tag);
			if (idx >= 0) {
				chapters[idx]!.status = status === "completed" ? "completed" : "partial";
				chapters[idx]!.confidence = confidence;
			}

			// Mark next pending chapter as generating
			const nextPending = chapters.find((c) => c.status === "pending");
			if (nextPending) {
				nextPending.status = "generating";
			}
			return;
		}

		if (eventType === "done") {
			reportDone = true;
			reportStatus = data.status as string;
			hasPdf = !!data.pdf_storage_key;

			for (const ch of chapters) {
				if (ch.status === "generating" || ch.status === "pending") {
					ch.status = reportStatus === "failed" ? "failed" : "completed";
				}
			}
			return;
		}

		if (eventType === "error") {
			error = (data.error as string) ?? "Report generation failed";
			reportDone = true;
			reportStatus = "failed";

			for (const ch of chapters) {
				if (ch.status === "generating" || ch.status === "pending") {
					ch.status = "failed";
				}
			}
		}
	}

	// ── Download PDF ─────────────────────────────────────────────────
	async function downloadPdf() {
		if (!jobId) return;
		downloading = true;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(
				`/reporting/model-portfolios/${portfolioId}/long-form-report/${jobId}/pdf`,
			);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `long-form-dd-${portfolioName.toLowerCase().replace(/\s+/g, "-")}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			error = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloading = false;
		}
	}

	// ── Chapter status helpers ───────────────────────────────────────
	function chapterIcon(status: ChapterStatus): string {
		switch (status) {
			case "completed":
				return "\u25CF";
			case "partial":
				return "\u25D0";
			case "generating":
				return "\u25CC";
			case "failed":
				return "\u2715";
			default:
				return "\u25CB";
		}
	}

	function chapterColor(status: ChapterStatus): string {
		switch (status) {
			case "completed":
				return "var(--ii-success)";
			case "partial":
				return "var(--ii-warning)";
			case "generating":
				return "var(--ii-brand-primary)";
			case "failed":
				return "var(--ii-danger)";
			default:
				return "var(--ii-text-muted)";
		}
	}
</script>

<div class="lfr">
	{#if error}
		<div class="lfr-error">
			{error}
			<button class="lfr-error-dismiss" onclick={() => (error = null)}>dismiss</button>
		</div>
	{/if}

	{#if !streaming && !reportDone}
		<div class="lfr-trigger">
			<p class="lfr-desc">
				Generate a comprehensive 8-chapter due diligence report covering macro context,
				allocation rationale, performance attribution, risk decomposition, and more.
			</p>
			<Button size="sm" onclick={generateReport} disabled={generating || !portfolioId}>
				{generating ? "Starting\u2026" : "Generate Long-Form Report"}
			</Button>
		</div>
	{/if}

	{#if chapters.length > 0}
		<div class="lfr-chapters">
			<div class="lfr-header">
				<span class="lfr-title">Long-Form Report</span>
				{#if streaming}
					<span class="lfr-progress">{completedCount} / 8 chapters</span>
				{:else if reportDone}
					<StatusBadge status={reportStatus ?? "completed"} />
				{/if}
			</div>

			<div class="lfr-list">
				{#each chapters as ch (ch.tag)}
					<div class="lfr-chapter" class:lfr-chapter--active={ch.status === "generating"}>
						<span class="lfr-chapter-icon" style:color={chapterColor(ch.status)}>
							{chapterIcon(ch.status)}
						</span>
						<span class="lfr-chapter-label">
							Chapter {ch.order} &mdash; {ch.title}
						</span>
						<span class="lfr-chapter-status">
							{#if ch.status === "generating"}
								<Spinner class="size-3" /> Generating&hellip;
							{:else if ch.status === "completed" && ch.confidence !== null}
								{formatPercent(ch.confidence)}
							{:else if ch.status === "partial"}
								<StatusBadge status="partial" />
							{:else if ch.status === "failed"}
								<StatusBadge status="failed" />
							{/if}
						</span>
					</div>
				{/each}
			</div>

			{#if reportDone}
				<div class="lfr-footer">
					{#if reportStatus === "partial"}
						<p class="lfr-warning">
							Some chapters had issues but the report is still available.
						</p>
					{/if}
					<div class="lfr-actions">
						{#if hasPdf}
							<Button size="sm" onclick={downloadPdf} disabled={downloading}>
								{downloading ? "Downloading\u2026" : "Download PDF"}
							</Button>
						{:else if reportStatus !== "failed"}
							<span class="lfr-no-pdf">PDF generation is pending. Try again shortly.</span>
						{/if}
						<Button size="sm" variant="outline" onclick={generateReport}>
							Generate New Report
						</Button>
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.lfr {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-md, 16px);
	}

	.lfr-error {
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
		border-radius: var(--ii-radius-sm, 8px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.lfr-error-dismiss {
		background: none;
		border: none;
		color: inherit;
		cursor: pointer;
		text-decoration: underline;
		font-size: var(--ii-text-label, 0.75rem);
		font-family: var(--ii-font-sans);
	}

	.lfr-trigger {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--ii-space-inline-md, 16px);
	}

	.lfr-desc {
		margin: 0;
		color: var(--ii-text-secondary);
		font-size: var(--ii-text-small, 0.8125rem);
		max-width: 520px;
	}

	/* ── Chapter list ───────────────────────────────────────────────── */
	.lfr-chapters {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		overflow: hidden;
	}

	.lfr-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		background: var(--ii-surface-alt);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.lfr-title {
		font-weight: 600;
		font-size: var(--ii-text-body, 0.9375rem);
		color: var(--ii-text-primary);
	}

	.lfr-progress {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.lfr-list {
		padding: 0;
	}

	.lfr-chapter {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 8px);
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.lfr-chapter:last-child {
		border-bottom: none;
	}

	.lfr-chapter--active {
		background: color-mix(in srgb, var(--ii-brand-primary) 4%, transparent);
	}

	.lfr-chapter-icon {
		font-size: 10px;
		width: 16px;
		text-align: center;
		flex-shrink: 0;
	}

	.lfr-chapter-label {
		flex: 1;
		color: var(--ii-text-primary);
	}

	.lfr-chapter-status {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
	}


	/* ── Footer ──────────────────────────────────────────────────────── */
	.lfr-footer {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		border-top: 1px solid var(--ii-border-subtle);
	}

	.lfr-warning {
		margin: 0 0 var(--ii-space-stack-xs, 8px);
		color: var(--ii-warning);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.lfr-actions {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 8px);
	}

	.lfr-no-pdf {
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}
</style>
