<!--
  ReportsPanel — terminal-native content generation surface.

  Renders existing reports (outlooks, flash reports, spotlights)
  with generate buttons, SSE streaming progress, and PDF download.
  Uses createTerminalStream for SSE, createClientApiClient for auth.
-->
<script lang="ts">
	import { getContext, onDestroy, onMount } from "svelte";
	import { formatDateTime } from "@investintell/ui";
	import { createClientApiClient } from "$wealth/api/client";
	import { createTerminalStream, type TerminalStreamHandle } from "$wealth/components/terminal/runtime/stream";
	import LiveDot from "$wealth/components/terminal/data/LiveDot.svelte";
	import type { ContentSummary } from "$wealth/types/content";
	import { contentTypeLabel } from "$wealth/types/content";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	// ── State ─────────────────────────────────────────────────────
	let reports = $state<ContentSummary[]>([]);
	let loading = $state(true);
	let errorMsg = $state<string | null>(null);
	let generating = $state(false);
	let downloadingId = $state<string | null>(null);

	// Fund picker for spotlight
	let spotlightOpen = $state(false);
	let spotlightSearch = $state("");
	let fundResults = $state<{ fund_id: string; name: string; manager_name?: string | null }[]>([]);
	let fundLoading = $state(false);

	// SSE handles
	let activeStreamHandle = $state<TerminalStreamHandle | null>(null);
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	// ── Lifecycle ─────────────────────────────────────────────────

	onMount(async () => {
		await fetchReports();
	});

	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
		activeStreamHandle?.close();
	});

	// Poll while any item is generating
	let hasGenerating = $derived(reports.some((r) => r.status === "draft" || r.status === "generating"));

	$effect(() => {
		if (hasGenerating && !pollTimer) {
			pollTimer = setInterval(() => { void fetchReports(); }, 5000);
		} else if (!hasGenerating && pollTimer) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	});

	// ── Data fetching ─────────────────────────────────────────────

	async function fetchReports() {
		try {
			reports = await api.get<ContentSummary[]>("/content");
			errorMsg = null;
		} catch (err: unknown) {
			if (loading) {
				errorMsg = err instanceof Error ? err.message : "Failed to load reports";
			}
		} finally {
			loading = false;
		}
	}

	// ── Generation ────────────────────────────────────────────────

	async function generateContent(endpoint: string, params?: Record<string, string>) {
		generating = true;
		errorMsg = null;
		try {
			const qs = params ? "?" + new URLSearchParams(params).toString() : "";
			const res = await api.post<ContentSummary & { job_id?: string }>(`/content/${endpoint}${qs}`, {});
			await fetchReports();
			if (res.job_id && res.id) {
				startSSE(String(res.id), res.job_id);
			}
		} catch (err: unknown) {
			if (err instanceof Error && err.message.includes("409")) {
				errorMsg = "A flash report was already generated recently. Please wait before generating another.";
			} else {
				errorMsg = err instanceof Error ? err.message : "Generation failed";
			}
		} finally {
			generating = false;
		}
	}

	function startSSE(contentId: string, jobId: string) {
		const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
		const abortController = new AbortController();

		// Get token async and start stream
		(async () => {
			const token = await getToken();
			activeStreamHandle = createTerminalStream<Record<string, unknown>>({
				url: `${apiBase}/content/${contentId}/stream/${jobId}`,
				headers: { Authorization: `Bearer ${token}` },
				signal: abortController.signal,
				reconnect: false,
				onMessage: (data) => {
					if (data.type === "done" || data.type === "error") {
						void fetchReports();
						activeStreamHandle?.close();
					}
				},
				onError: () => {
					void fetchReports();
				},
				onClose: () => {
					activeStreamHandle = null;
				},
			});
		})();
	}

	// ── Spotlight fund picker ────────────────────────────────────

	function openSpotlightPicker() {
		spotlightOpen = true;
		spotlightSearch = "";
		fundResults = [];
	}

	async function searchFunds() {
		if (!spotlightSearch.trim()) {
			fundResults = [];
			return;
		}
		fundLoading = true;
		try {
			fundResults = await api.get<typeof fundResults>(`/funds?q=${encodeURIComponent(spotlightSearch.trim())}&limit=10`);
		} catch {
			fundResults = [];
		} finally {
			fundLoading = false;
		}
	}

	let searchDebounce: ReturnType<typeof setTimeout> | null = null;

	function handleSearchInput() {
		if (searchDebounce) clearTimeout(searchDebounce);
		searchDebounce = setTimeout(searchFunds, 300);
	}

	async function selectSpotlightFund(fundId: string) {
		spotlightOpen = false;
		await generateContent("spotlights", { instrument_id: fundId });
	}

	// ── Download ──────────────────────────────────────────────────

	async function downloadPdf(item: ContentSummary) {
		downloadingId = item.id;
		try {
			const blob = await api.getBlob(`/content/${item.id}/download`);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `${item.content_type}_${item.language}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (err: unknown) {
			errorMsg = err instanceof Error ? err.message : "Download failed";
		} finally {
			downloadingId = null;
		}
	}

	// ── Retry ─────────────────────────────────────────────────────

	function retryContent(item: ContentSummary) {
		if (item.content_type === "manager_spotlight") {
			openSpotlightPicker();
			return;
		}
		const endpointMap: Record<string, string> = {
			investment_outlook: "outlooks",
			flash_report: "flash-reports",
		};
		const endpoint = endpointMap[item.content_type];
		if (endpoint) void generateContent(endpoint);
	}

	// ── Status helpers ────────────────────────────────────────────

	function statusLabel(s: string): string {
		switch (s) {
			case "draft":
			case "generating": return "GENERATING";
			case "ready":
			case "published": return "PUBLISHED";
			case "failed": return "FAILED";
			default: return s.toUpperCase();
		}
	}

	type DotStatus = "success" | "warn" | "error" | "muted";

	function statusDot(s: string): DotStatus {
		switch (s) {
			case "draft":
			case "generating": return "warn";
			case "ready":
			case "published": return "success";
			case "failed": return "error";
			default: return "muted";
		}
	}
</script>

<div class="rp-root">
	<!-- Generate bar -->
	<div class="rp-generate-bar">
		<span class="rp-generate-label">GENERATE:</span>
		<button
			class="rp-gen-btn"
			onclick={() => generateContent("outlooks")}
			disabled={generating}
		>
			[ OUTLOOK ]
		</button>
		<button
			class="rp-gen-btn"
			onclick={() => generateContent("flash-reports")}
			disabled={generating}
		>
			[ FLASH ]
		</button>
		<button
			class="rp-gen-btn"
			onclick={openSpotlightPicker}
			disabled={generating}
		>
			[ SPOTLIGHT ]
		</button>
	</div>

	{#if errorMsg}
		<div class="rp-error">
			<span>{errorMsg}</span>
			<button class="rp-error-dismiss" onclick={() => errorMsg = null} type="button">x</button>
		</div>
	{/if}

	<!-- Report list -->
	<div class="rp-list">
		{#if loading}
			<div class="rp-empty">
				<span class="rp-empty-text">Loading reports...</span>
			</div>
		{:else if reports.length === 0}
			<div class="rp-empty">
				<span class="rp-empty-text">No reports yet. Generate an outlook or flash report to start.</span>
			</div>
		{:else}
			{#each reports as item (item.id)}
				<div class="rp-card">
					<div class="rp-card-top">
						<div class="rp-card-info">
							<span class="rp-card-type">{contentTypeLabel(item.content_type)}</span>
							<span class="rp-card-title">{item.title ?? contentTypeLabel(item.content_type)}</span>
						</div>
						<div class="rp-card-meta">
							<span class="rp-card-lang">{item.language.toUpperCase()}</span>
							<span class="rp-card-date">{formatDateTime(item.created_at)}</span>
						</div>
					</div>
					<div class="rp-card-bottom">
						<div class="rp-card-status">
							<LiveDot
								status={statusDot(item.status)}
								pulse={item.status === "draft" || item.status === "generating"}
							/>
							<span class="rp-status-text">{statusLabel(item.status)}</span>
						</div>
						<div class="rp-card-actions">
							{#if item.status === "draft" || item.status === "generating"}
								<span class="rp-btn rp-btn-generating">[ GENERATING... ]</span>
							{:else if item.status === "published" || item.status === "ready"}
								<button
									class="rp-btn rp-btn-download"
									onclick={() => downloadPdf(item)}
									disabled={downloadingId === item.id}
								>
									{downloadingId === item.id ? "[ DOWNLOADING... ]" : "[ DOWNLOAD PDF ]"}
								</button>
							{:else if item.status === "failed"}
								<button class="rp-btn rp-btn-retry" onclick={() => retryContent(item)}>
									[ REGENERATE ]
								</button>
							{/if}
						</div>
					</div>
				</div>
			{/each}
		{/if}
	</div>
</div>

<!-- Spotlight fund picker dialog -->
{#if spotlightOpen}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="rp-overlay" onclick={() => spotlightOpen = false}>
		<div class="rp-dialog" onclick={(e) => e.stopPropagation()}>
			<div class="rp-dialog-header">
				<span class="rp-dialog-title">SELECT FUND FOR SPOTLIGHT</span>
				<button class="rp-dialog-close" onclick={() => spotlightOpen = false}>x</button>
			</div>
			<div class="rp-dialog-body">
				<input
					type="text"
					class="rp-dialog-search"
					placeholder="Search funds..."
					bind:value={spotlightSearch}
					oninput={handleSearchInput}
				/>
				{#if fundLoading}
					<div class="rp-dialog-msg">Searching...</div>
				{:else if spotlightSearch && fundResults.length === 0}
					<div class="rp-dialog-msg">No funds found</div>
				{:else}
					<div class="rp-dialog-results">
						{#each fundResults as fund (fund.fund_id)}
							<button
								class="rp-dialog-fund"
								onclick={() => selectSpotlightFund(fund.fund_id)}
							>
								<span class="rp-fund-name">{fund.name}</span>
								{#if fund.manager_name}
									<span class="rp-fund-manager">{fund.manager_name}</span>
								{/if}
							</button>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.rp-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
		overflow: hidden;
	}

	/* ── Generate bar ── */
	.rp-generate-bar {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 12px 16px;
		border-bottom: var(--terminal-border-hairline);
		flex-shrink: 0;
	}

	.rp-generate-label {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0.1em;
		color: var(--terminal-fg-muted);
		text-transform: uppercase;
	}

	.rp-gen-btn {
		background: transparent;
		border: var(--terminal-border-hairline);
		color: var(--terminal-accent-cyan);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0.05em;
		padding: 4px 10px;
		cursor: pointer;
		transition: all 150ms ease;
		outline: none;
	}

	.rp-gen-btn:hover:not(:disabled) {
		background: color-mix(in srgb, var(--terminal-accent-cyan) 10%, transparent);
		border-color: var(--terminal-accent-cyan);
	}

	.rp-gen-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	/* ── Error banner ── */
	.rp-error {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 16px;
		background: color-mix(in srgb, var(--terminal-status-error) 10%, transparent);
		color: var(--terminal-status-error);
		font-size: var(--terminal-text-11);
		border-bottom: var(--terminal-border-hairline);
	}

	.rp-error-dismiss {
		background: none;
		border: none;
		color: var(--terminal-status-error);
		cursor: pointer;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		padding: 0 4px;
	}

	/* ── Report list ── */
	.rp-list {
		flex: 1;
		overflow-y: auto;
		padding: 8px 0;
	}

	.rp-card {
		border-bottom: var(--terminal-border-hairline);
		padding: 10px 16px;
	}

	.rp-card-top {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 6px;
	}

	.rp-card-info {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.rp-card-type {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		color: var(--terminal-accent-cyan);
		text-transform: uppercase;
	}

	.rp-card-title {
		font-size: var(--terminal-text-12);
		font-weight: 600;
		color: var(--terminal-fg-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.rp-card-meta {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-shrink: 0;
	}

	.rp-card-lang {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.05em;
		color: var(--terminal-fg-tertiary);
	}

	.rp-card-date {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
		font-variant-numeric: tabular-nums;
	}

	.rp-card-bottom {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	.rp-card-status {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.rp-status-text {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		color: var(--terminal-fg-secondary);
	}

	.rp-card-actions {
		display: flex;
		gap: 8px;
	}

	/* ── Action buttons ── */
	.rp-btn {
		background: transparent;
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0.05em;
		padding: 3px 8px;
		cursor: pointer;
		transition: all 150ms ease;
		outline: none;
	}

	.rp-btn-generating {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
		cursor: default;
		animation: rp-pulse 1.5s infinite alternate;
	}

	@keyframes rp-pulse {
		0% { opacity: 0.5; }
		100% { opacity: 1; }
	}

	.rp-btn-download {
		color: var(--terminal-accent-cyan);
		border-color: var(--terminal-accent-cyan);
	}

	.rp-btn-download:hover:not(:disabled) {
		background: color-mix(in srgb, var(--terminal-accent-cyan) 10%, transparent);
	}

	.rp-btn-download:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.rp-btn-retry {
		color: var(--terminal-status-error);
		border-color: var(--terminal-status-error);
	}

	.rp-btn-retry:hover {
		background: color-mix(in srgb, var(--terminal-status-error) 10%, transparent);
	}

	/* ── Empty state ── */
	.rp-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		padding: 24px;
	}

	.rp-empty-text {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
		letter-spacing: 0.04em;
	}

	/* ── Spotlight dialog ── */
	.rp-overlay {
		position: fixed;
		inset: 0;
		z-index: var(--terminal-z-modal, 1000);
		background: rgba(0, 0, 0, 0.6);
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.rp-dialog {
		width: 420px;
		max-height: 480px;
		display: flex;
		flex-direction: column;
		background: var(--terminal-bg-surface);
		border: var(--terminal-border-hairline);
		overflow: hidden;
	}

	.rp-dialog-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 14px;
		border-bottom: var(--terminal-border-hairline);
	}

	.rp-dialog-title {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0.1em;
		color: var(--terminal-fg-secondary);
	}

	.rp-dialog-close {
		background: none;
		border: none;
		color: var(--terminal-fg-muted);
		cursor: pointer;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-12);
		padding: 2px 4px;
	}

	.rp-dialog-body {
		display: flex;
		flex-direction: column;
		padding: 10px 14px;
		gap: 8px;
		overflow: hidden;
	}

	.rp-dialog-search {
		width: 100%;
		padding: 6px 10px;
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-primary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		outline: none;
	}

	.rp-dialog-search::placeholder {
		color: var(--terminal-fg-muted);
	}

	.rp-dialog-search:focus {
		border-color: var(--terminal-accent-cyan);
	}

	.rp-dialog-msg {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
		padding: 8px 0;
	}

	.rp-dialog-results {
		display: flex;
		flex-direction: column;
		overflow-y: auto;
		max-height: 320px;
	}

	.rp-dialog-fund {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: 6px 8px;
		background: transparent;
		border: none;
		border-bottom: var(--terminal-border-hairline);
		cursor: pointer;
		text-align: left;
		font-family: var(--terminal-font-mono);
		transition: background 100ms ease;
	}

	.rp-dialog-fund:hover {
		background: var(--terminal-bg-panel-raised);
	}

	.rp-fund-name {
		font-size: var(--terminal-text-11);
		font-weight: 600;
		color: var(--terminal-fg-primary);
	}

	.rp-fund-manager {
		font-size: 9px;
		color: var(--terminal-fg-muted);
	}
</style>
