<!--
  /dd/[reportId] — DD Report Viewer (Phase 6, Session B).

  Two-column layout: left (75%) shows report header + collapsible chapters,
  right (25%) shows actions panel + audit trail. SSE stream for real-time
  chapter generation. Terminal-native primitives only — no shadcn.
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { getContext } from "svelte";
	import { goto } from "$app/navigation";
	import { resolve } from "$app/paths";
	import { formatDateTime, formatPercent } from "@investintell/ui";
	import { createClientApiClient } from "$wealth/api/client";
	import { createTerminalStream } from "$wealth/components/terminal/runtime/stream";
	import Panel from "$wealth/components/terminal/layout/Panel.svelte";
	import PanelHeader from "$wealth/components/terminal/layout/PanelHeader.svelte";
	import LiveDot from "$wealth/components/terminal/data/LiveDot.svelte";
	import DDChapterSection from "$wealth/components/terminal/dd/DDChapterSection.svelte";
	import DDApprovalDialog from "$wealth/components/terminal/dd/DDApprovalDialog.svelte";
	import type { DDReportFull, DDChapter, AuditEvent } from "$wealth/types/dd-report";
	import { chapterTitle } from "$wealth/types/dd-report";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);
	const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

	const reportId = $derived($page.params.reportId);

	// ── Report state ─────────────────────────────────────────────────
	let report = $state<DDReportFull | null>(null);
	let loading = $state(true);
	let loadError = $state<string | null>(null);

	async function loadReport() {
		loading = true;
		loadError = null;
		try {
			report = await api.get<DDReportFull>(`/dd-reports/${reportId}`);
		} catch (err: unknown) {
			loadError = err instanceof Error ? err.message : "Failed to load DD report.";
			report = null;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void reportId;
		void loadReport();
	});

	// ── Chapters ─────────────────────────────────────────────────────
	const chapters = $derived(
		((report?.chapters ?? []) as DDChapter[]).toSorted(
			(a, b) => a.chapter_order - b.chapter_order,
		),
	);
	const completedChapters = $derived(
		chapters.filter((c) => c.content_md !== null).length,
	);
	const totalExpected = 8;

	// Track which chapters are currently generating via SSE
	let generatingTags = $state<Set<string>>(new Set());

	// ── SSE stream ───────────────────────────────────────────────────
	interface GenerationEvent {
		type: string;
		chapter_tag?: string;
		order?: number;
		status?: string;
		confidence_score?: number;
		decision_anchor?: string;
		error?: string;
	}

	let streamHandle: ReturnType<typeof createTerminalStream<GenerationEvent>> | null = null;

	$effect(() => {
		if (report?.status !== "generating") {
			streamHandle?.close();
			streamHandle = null;
			return;
		}

		// Start SSE stream for generating reports
		let abortController = new AbortController();

		(async () => {
			const token = await getToken();
			streamHandle = createTerminalStream<GenerationEvent>({
				url: `${apiBase}/dd-reports/${reportId}/stream`,
				headers: { Authorization: `Bearer ${token}` },
				signal: abortController.signal,
				reconnect: true,
				onMessage(event) {
					if (event.type === "chapter_started" && event.chapter_tag) {
						generatingTags = new Set([...generatingTags, event.chapter_tag]);
					}
					if (event.type === "chapter_completed" && event.chapter_tag) {
						// eslint-disable-next-line svelte/prefer-svelte-reactivity -- wealth parity: generatingTags is reassigned (not mutated); plain Set is safe here.
						const next = new Set(generatingTags);
						next.delete(event.chapter_tag);
						generatingTags = next;
						// Refresh report to get updated chapter content
						void loadReport();
					}
					if (event.type === "report_completed" || event.type === "report_failed") {
						generatingTags = new Set();
						void loadReport();
					}
				},
				onError(err) {
					console.error("DD SSE error:", err);
				},
			});
		})();

		return () => {
			abortController.abort();
			streamHandle?.close();
			streamHandle = null;
		};
	});

	// ── Status mappings (shared with Session A) ──────────────────────
	const STATUS_LABELS: Record<string, string> = {
		draft: "Queued",
		generating: "Generating...",
		pending_approval: "Pending Review",
		approved: "Approved",
		rejected: "Rejected",
		failed: "Failed",
	};

	const STATUS_COLORS: Record<string, string> = {
		draft: "var(--terminal-fg-secondary)",
		generating: "var(--terminal-accent-amber)",
		pending_approval: "var(--terminal-accent-cyan)",
		approved: "var(--terminal-status-success)",
		rejected: "var(--terminal-status-error)",
		failed: "var(--terminal-status-error)",
	};

	const ANCHOR_LABELS: Record<string, { text: string; color: string }> = {
		APPROVE: { text: "Recommend Approve", color: "var(--terminal-status-success)" },
		REJECT: { text: "Recommend Reject", color: "var(--terminal-status-error)" },
		CONDITIONAL: { text: "Conditional", color: "var(--terminal-accent-amber)" },
	};

	const statusLabel = $derived(STATUS_LABELS[report?.status ?? ""] ?? report?.status ?? "");
	const statusColor = $derived(STATUS_COLORS[report?.status ?? ""] ?? "var(--terminal-fg-secondary)");
	const anchor = $derived(report?.decision_anchor ? ANCHOR_LABELS[report.decision_anchor] ?? null : null);

	// ── Confidence bar ───────────────────────────────────────────────
	function confidenceBarColor(score: number): string {
		if (score < 50) return "var(--terminal-status-error)";
		if (score <= 75) return "var(--terminal-accent-amber)";
		return "var(--terminal-status-success)";
	}

	// ── Approval logic ───────────────────────────────────────────────
	const IC_ROLES = ["admin", "super_admin", "investment_team"];
	const actor = $derived($page.data.actor);
	const canApprove = $derived(
		report !== null &&
		report.status === "pending_approval" &&
		actor?.role !== null &&
		IC_ROLES.includes(actor?.role ?? ""),
	);

	let approveDialogOpen = $state(false);
	let rejectDialogOpen = $state(false);
	let approvalSubmitting = $state(false);
	let approvalError = $state<string | null>(null);

	async function handleApprove(rationale: string) {
		approvalSubmitting = true;
		approvalError = null;
		try {
			await api.post(`/dd-reports/${reportId}/approve`, { rationale });
			approveDialogOpen = false;
			await loadReport();
			await loadAuditTrail();
		} catch (err: unknown) {
			if (err instanceof Error && err.message.includes("403")) {
				approvalError = "Self-approval is not permitted.";
			} else {
				approvalError = err instanceof Error ? err.message : "Approval failed.";
			}
		} finally {
			approvalSubmitting = false;
		}
	}

	async function handleReject(reason: string) {
		approvalSubmitting = true;
		approvalError = null;
		try {
			await api.post(`/dd-reports/${reportId}/reject`, { reason });
			rejectDialogOpen = false;
			await loadReport();
			await loadAuditTrail();
		} catch (err: unknown) {
			approvalError = err instanceof Error ? err.message : "Rejection failed.";
		} finally {
			approvalSubmitting = false;
		}
	}

	// ── Audit trail ──────────────────────────────────────────────────
	let auditEvents = $state<AuditEvent[]>([]);
	let auditLoading = $state(true);

	const AUDIT_LABELS: Record<string, string> = {
		"dd_report.approve": "Approved",
		"dd_report.reject": "Rejected",
		"dd_report.approve.override": "Approved (Override)",
		"dd_report.reject.override": "Rejected (Override)",
		"dd_report.create": "Created",
		"dd_report.generate": "Generation Started",
	};

	async function loadAuditTrail() {
		auditLoading = true;
		try {
			auditEvents = await api.get<AuditEvent[]>(`/dd-reports/${reportId}/audit-trail`);
		} catch {
			auditEvents = [];
		} finally {
			auditLoading = false;
		}
	}

	$effect(() => {
		void reportId;
		void loadAuditTrail();
	});

	// ── Navigation ───────────────────────────────────────────────────
	const DD_QUEUE = resolve("/dd");
</script>

<div class="ddv-root">
	{#if loading && !report}
		<div class="ddv-loading">Loading report...</div>
	{:else if loadError && !report}
		<div class="ddv-error">{loadError}</div>
	{:else if report}
		<div class="ddv-layout">
			<!-- LEFT COLUMN (75%) -->
			<div class="ddv-main">
				<!-- Back link -->
				<a class="ddv-back" href={DD_QUEUE}>
					&lt; BACK TO QUEUE
				</a>

				<!-- Report header -->
				<div class="ddv-header">
					<div class="ddv-header-top">
						<span class="ddv-fund-name">
							{report.config_snapshot?.instrument_label ?? "DD Report"}
						</span>
						<span class="ddv-meta">
							<span class="ddv-version">v{report.version}</span>
							<span class="ddv-status" style:color={statusColor}>{statusLabel}</span>
							{#if report.status === "generating"}
								<LiveDot status="warn" pulse label="Generating" />
							{/if}
						</span>
					</div>

					{#if report.confidence_score !== null}
						<div class="ddv-confidence">
							<span class="ddv-confidence-label">
								Confidence: {formatPercent(report.confidence_score / 100, 0)}
							</span>
							<div class="ddv-confidence-track">
								<div
									class="ddv-confidence-fill"
									style:width="{Math.min(100, Math.max(0, report.confidence_score))}%"
									style:background={confidenceBarColor(report.confidence_score)}
								></div>
							</div>
						</div>
					{/if}

					{#if anchor}
						<span class="ddv-anchor" style:color={anchor.color}>{anchor.text}</span>
					{/if}

					{#if report.status === "generating"}
						<div class="ddv-progress">
							Chapters: {completedChapters} / {totalExpected}
						</div>
					{/if}
				</div>

				<!-- Chapters -->
				<div class="ddv-chapters">
					{#each chapters as chapter, i (chapter.id)}
						<DDChapterSection
							chapterTag={chapter.chapter_tag}
							chapterOrder={chapter.chapter_order}
							contentMd={chapter.content_md}
							evidenceRefs={chapter.evidence_refs}
							quantData={chapter.quant_data}
							criticIterations={chapter.critic_iterations}
							criticStatus={chapter.critic_status}
							generatedAt={chapter.generated_at}
							isGenerating={generatingTags.has(chapter.chapter_tag)}
							defaultOpen={i === 0}
						/>
					{:else}
						<div class="ddv-no-chapters">No chapters available.</div>
					{/each}
				</div>
			</div>

			<!-- RIGHT COLUMN (25%) -->
			<div class="ddv-sidebar">
				<!-- Actions panel -->
				<Panel>
					{#snippet header()}
						<PanelHeader label="ACTIONS" />
					{/snippet}

					<div class="ddv-actions-body">
						{#if report.status === "pending_approval" && canApprove}
							<button
								class="ddv-action-btn ddv-action-btn--approve"
								type="button"
								onclick={() => { approveDialogOpen = true; approvalError = null; }}
							>
								APPROVE
							</button>
							<button
								class="ddv-action-btn ddv-action-btn--reject"
								type="button"
								onclick={() => { rejectDialogOpen = true; approvalError = null; }}
							>
								REJECT
							</button>
						{:else if report.status === "pending_approval" && !canApprove}
							<div class="ddv-action-info">Awaiting IC review.</div>
						{:else if report.status === "approved"}
							<div class="ddv-action-info ddv-action-info--success">
								Approved{#if report.approved_by} by {report.approved_by}{/if}
								{#if report.approved_at}
									<br />{formatDateTime(report.approved_at)}
								{/if}
							</div>
						{:else if report.status === "rejected"}
							<div class="ddv-action-info ddv-action-info--error">
								Rejected
								{#if report.rejection_reason}
									<br /><span class="ddv-rejection-reason">{report.rejection_reason}</span>
								{/if}
							</div>
						{:else if report.status === "generating"}
							<div class="ddv-action-info">
								<LiveDot status="warn" pulse label="Generating" />
								<span>Report generation in progress...</span>
							</div>
						{:else if report.status === "draft"}
							<div class="ddv-action-info">Queued for generation.</div>
						{:else if report.status === "failed"}
							<div class="ddv-action-info ddv-action-info--error">Generation failed.</div>
						{/if}
					</div>
				</Panel>

				<!-- Audit trail -->
				<Panel scrollable>
					{#snippet header()}
						<PanelHeader label="AUDIT TRAIL" />
					{/snippet}

					<div class="ddv-audit">
						{#if auditLoading}
							<div class="ddv-audit-loading">Loading...</div>
						{:else if auditEvents.length === 0}
							<div class="ddv-audit-empty">No audit events.</div>
						{:else}
							{#each auditEvents as event (event.id)}
								<div class="ddv-audit-event">
									<span class="ddv-audit-action">
										{AUDIT_LABELS[event.action] ?? event.action}
									</span>
									{#if event.actor_id}
										<span class="ddv-audit-actor">{event.actor_id}</span>
									{/if}
									{#if event.created_at}
										<span class="ddv-audit-time">{formatDateTime(event.created_at)}</span>
									{/if}
								</div>
							{/each}
						{/if}
					</div>
				</Panel>
			</div>
		</div>
	{/if}
</div>

<!-- Approval dialogs -->
<DDApprovalDialog
	mode="approve"
	isOpen={approveDialogOpen}
	isSubmitting={approvalSubmitting}
	error={approvalError}
	onSubmit={handleApprove}
	onCancel={() => { approveDialogOpen = false; }}
/>

<DDApprovalDialog
	mode="reject"
	isOpen={rejectDialogOpen}
	isSubmitting={approvalSubmitting}
	error={approvalError}
	onSubmit={handleReject}
	onCancel={() => { rejectDialogOpen = false; }}
/>

<style>
	.ddv-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		font-family: var(--terminal-font-mono);
		overflow: hidden;
	}

	.ddv-loading,
	.ddv-error {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.ddv-error {
		color: var(--terminal-status-error);
	}

	.ddv-layout {
		display: grid;
		grid-template-columns: 1fr 280px;
		gap: var(--terminal-space-3);
		width: 100%;
		height: 100%;
		min-height: 0;
	}

	@media (min-width: 1400px) {
		.ddv-layout {
			grid-template-columns: 3fr 1fr;
		}
	}

	/* ── Left column ─────────────────────────────────── */
	.ddv-main {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-3);
		min-height: 0;
		overflow-y: auto;
	}

	.ddv-back {
		display: inline-block;
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-accent-cyan);
		text-decoration: none;
		padding: var(--terminal-space-1) 0;
	}

	.ddv-back:hover {
		text-decoration: underline;
	}

	.ddv-header {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-3);
		background: var(--terminal-bg-surface);
		border: var(--terminal-border-hairline);
	}

	.ddv-header-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--terminal-space-3);
	}

	.ddv-fund-name {
		font-size: var(--terminal-text-13);
		font-weight: 700;
		color: var(--terminal-fg-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.ddv-meta {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		flex-shrink: 0;
	}

	.ddv-version {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		font-weight: 600;
	}

	.ddv-status {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.ddv-confidence {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
	}

	.ddv-confidence-label {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		color: var(--terminal-fg-secondary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		flex-shrink: 0;
	}

	.ddv-confidence-track {
		flex: 1;
		height: 4px;
		background: var(--terminal-bg-panel);
		max-width: 200px;
	}

	.ddv-confidence-fill {
		height: 100%;
		transition: width var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.ddv-anchor {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.ddv-progress {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.ddv-chapters {
		display: flex;
		flex-direction: column;
	}

	/* Collapse double borders between adjacent chapter sections */
	.ddv-chapters :global(.dcs-root + .dcs-root) {
		border-top: none;
	}

	.ddv-no-chapters {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
		padding: var(--terminal-space-3);
	}

	/* ── Right column ────────────────────────────────── */
	.ddv-sidebar {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-3);
		min-height: 0;
		overflow-y: auto;
	}

	.ddv-actions-body {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
	}

	.ddv-action-btn {
		width: 100%;
		padding: var(--terminal-space-2) var(--terminal-space-3);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		background: transparent;
		border: 1px solid;
		border-radius: var(--terminal-radius-none);
		cursor: pointer;
		transition: opacity var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.ddv-action-btn:hover {
		opacity: 0.8;
	}

	.ddv-action-btn--approve {
		border-color: var(--terminal-status-success);
		color: var(--terminal-status-success);
	}

	.ddv-action-btn--reject {
		border-color: var(--terminal-status-error);
		color: var(--terminal-status-error);
	}

	.ddv-action-info {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
		line-height: 1.5;
	}

	.ddv-action-info--success {
		color: var(--terminal-status-success);
	}

	.ddv-action-info--error {
		color: var(--terminal-status-error);
	}

	.ddv-rejection-reason {
		font-style: italic;
		color: var(--terminal-fg-secondary);
	}

	/* ── Audit trail ─────────────────────────────────── */
	.ddv-audit {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
	}

	.ddv-audit-loading,
	.ddv-audit-empty {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
	}

	.ddv-audit-event {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: var(--terminal-space-1) 0;
		border-bottom: var(--terminal-border-hairline);
	}

	.ddv-audit-event:last-child {
		border-bottom: none;
	}

	.ddv-audit-action {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		color: var(--terminal-fg-primary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.ddv-audit-actor {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-secondary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.ddv-audit-time {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-muted);
	}
</style>
