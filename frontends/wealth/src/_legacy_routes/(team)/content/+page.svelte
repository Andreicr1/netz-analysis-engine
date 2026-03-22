<!--
  Content Production — trigger outlooks/flash reports/spotlights, approve/reject, download.
  Phase 3C: Status pipeline (generating→draft→pending_review→approved→published),
  SSE progress for generating state, ConsequenceDialog for approve/reject, download buttons.
-->
<script lang="ts">
	import { StatusBadge, PageHeader, EmptyState, Button, Card, Dialog, Select, FormField } from "@netz/ui";
	import { ActionButton, ConsequenceDialog } from "@netz/ui";
	import type { ConsequenceDialogPayload } from "@netz/ui";
	import { formatDate, formatDateTime } from "@netz/ui";
	import type { PageData } from "./$types";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import { resolveWealthStatus } from "$lib/utils/status-maps";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	import type { ContentSummary } from "$lib/types/api";

	let { data }: { data: PageData } = $props();

	let contentList = $derived((data.content ?? []) as ContentSummary[]);
	let hasGenerating = $derived(contentList.some(c => c.status === "generating"));

	let generating = $state(false);
	let downloadingId = $state<string | null>(null);
	let actionError = $state<string | null>(null);

	// ── ConsequenceDialog state ──
	let showApproveDialog = $state(false);
	let showRejectDialog = $state(false);
	let targetContentId = $state<string | null>(null);
	let targetContentTitle = $state<string>("Content");

	// ── SSE progress for generating items ──
	let sseProgress = $state<Record<string, { progress: number; message: string }>>({});
	let sseAbortControllers = $state<Record<string, AbortController>>({});

	async function connectSSEForItem(contentId: string) {
		const token = await getToken();
		const abortController = new AbortController();
		sseAbortControllers[contentId] = abortController;

		const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
		try {
			const response = await fetch(`${baseUrl}/content/${contentId}/progress`, {
				headers: {
					Authorization: `Bearer ${token}`,
					Accept: "text/event-stream",
				},
				signal: abortController.signal,
			});

			if (!response.ok || !response.body) return;

			const reader = response.body.getReader();
			const decoder = new TextDecoder();
			let buffer = "";

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split("\n");
				buffer = lines.pop() ?? "";

				for (const line of lines) {
					if (line.startsWith("data: ")) {
						try {
							const event = JSON.parse(line.slice(6));
							if (event.progress !== undefined) {
								sseProgress[contentId] = {
									progress: event.progress ?? 0,
									message: event.message ?? "",
								};
							}
							if (event.status === "completed" || event.status === "failed") {
								await invalidateAll();
								delete sseProgress[contentId];
								return;
							}
						} catch {
							// ignore malformed events
						}
					}
				}
			}
		} catch (e) {
			if (e instanceof Error && e.name === "AbortError") return;
			// SSE connection failed — fall back to polling
		} finally {
			delete sseAbortControllers[contentId];
		}
	}

	// Start SSE connections for generating items
	$effect(() => {
		for (const item of contentList) {
			if (item.status === "generating" && !sseAbortControllers[item.id]) {
				connectSSEForItem(item.id);
			}
		}
	});

	// Cleanup SSE on unmount
	$effect(() => {
		return () => {
			for (const ctrl of Object.values(sseAbortControllers)) {
				ctrl.abort();
			}
		};
	});

	// ── Polling fallback for generating items ──
	let pollTimer: ReturnType<typeof setInterval> | undefined;

	$effect(() => {
		if (hasGenerating) {
			pollTimer = setInterval(async () => {
				await invalidateAll();
			}, 10_000);
		} else if (pollTimer) {
			clearInterval(pollTimer);
			pollTimer = undefined;
		}
		return () => {
			if (pollTimer) {
				clearInterval(pollTimer);
				pollTimer = undefined;
			}
		};
	});

	// ── Spotlight Fund Picker ──
	let showSpotlightPicker = $state(false);
	let spotlightFundId = $state("");
	let funds = $state<Array<{ id: string; name: string }>>([]);
	let loadingFunds = $state(false);

	async function openSpotlightPicker() {
		showSpotlightPicker = true;
		if (funds.length === 0) {
			loadingFunds = true;
			try {
				const api = createClientApiClient(getToken);
				const res = await api.get<Array<{ id: string; name: string }>>("/funds");
				funds = Array.isArray(res) ? res : [];
			} catch {
				funds = [];
			} finally {
				loadingFunds = false;
			}
		}
	}

	async function triggerGeneration(type: string, extraParams?: string) {
		generating = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			const url = extraParams ? `/content/${type}?${extraParams}` : `/content/${type}`;
			await api.post(url, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Generation failed";
		} finally {
			generating = false;
		}
	}

	async function triggerSpotlight() {
		if (!spotlightFundId) return;
		showSpotlightPicker = false;
		await triggerGeneration("spotlights", `instrument_id=${spotlightFundId}`);
	}

	function openApproveDialog(item: ContentSummary) {
		targetContentId = item.id;
		targetContentTitle = item.title ?? item.content_type;
		showApproveDialog = true;
	}

	function openRejectDialog(item: ContentSummary) {
		targetContentId = item.id;
		targetContentTitle = item.title ?? item.content_type;
		showRejectDialog = true;
	}

	async function handleApprove(payload: ConsequenceDialogPayload) {
		if (!targetContentId) return;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/content/${targetContentId}/approve`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Approval failed";
		}
	}

	async function handleReject(payload: ConsequenceDialogPayload) {
		if (!targetContentId) return;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			// TODO: Backend /content/{id}/reject endpoint does not exist yet.
			// When implemented, send { rationale: payload.rationale }.
			await api.post(`/content/${targetContentId}/reject`, {
				rationale: payload.rationale ?? "",
			});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Rejection failed";
		}
	}

	async function downloadContent(contentId: string, title: string) {
		downloadingId = contentId;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(`/content/${contentId}/download`);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `${title || "content"}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloadingId = null;
		}
	}

	// ── Status pipeline stages ──
	const PIPELINE_STAGES = ["generating", "draft", "review", "approved", "published"] as const;

	function stageIndex(status: string): number {
		const idx = PIPELINE_STAGES.indexOf(status as typeof PIPELINE_STAGES[number]);
		return idx >= 0 ? idx : -1;
	}
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<PageHeader title="Content Production">
		{#snippet actions()}
			<div class="flex gap-2">
				<ActionButton onclick={() => triggerGeneration("outlooks")} loading={generating} loadingText="Generating...">
					Generate Outlook
				</ActionButton>
				<ActionButton onclick={() => triggerGeneration("flash-reports")} loading={generating} loadingText="Generating...">
					Flash Report
				</ActionButton>
				<Button onclick={openSpotlightPicker} disabled={generating}>
					Spotlight
				</Button>
			</div>
		{/snippet}
	</PageHeader>

	{#if actionError}
		<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	{#if contentList.length > 0}
		<div class="space-y-3">
			{#each contentList as item (item.id)}
				{@const currentStage = stageIndex(item.status)}
				{@const progress = sseProgress[item.id]}
				<Card class="p-4">
					<div class="flex items-start justify-between gap-4">
						<div class="flex-1">
							<div class="flex items-center gap-2">
								<p class="text-sm font-medium text-(--netz-text-primary)">
									{item.title ?? item.content_type}
								</p>
								<StatusBadge status={item.status} type="default" resolve={resolveWealthStatus} />
							</div>
							<p class="mt-1 text-xs text-(--netz-text-muted)">
								{item.content_type} &middot; {formatDate(item.created_at)}
							</p>

							{#if item.status === "failed" && item.error_message}
								<p class="mt-1 text-xs text-(--netz-status-error)">{item.error_message}</p>
							{/if}

							<!-- SSE progress bar for generating items -->
							{#if item.status === "generating"}
								<div class="mt-2">
									{#if progress}
										<div class="flex items-center gap-2">
											<div class="h-1.5 flex-1 overflow-hidden rounded-full bg-(--netz-surface-alt)">
												<div
													class="h-full rounded-full bg-(--netz-brand-primary) transition-all duration-500"
													style="width: {Math.min(progress.progress, 100)}%"
												></div>
											</div>
											<span class="text-xs text-(--netz-text-muted)">
												{Math.round(progress.progress)}%
											</span>
										</div>
										{#if progress.message}
											<p class="mt-1 text-xs text-(--netz-text-muted)">{progress.message}</p>
										{/if}
									{:else}
										<div class="flex items-center gap-2">
											<div class="h-1.5 flex-1 overflow-hidden rounded-full bg-(--netz-surface-alt)">
												<div class="h-full w-1/3 animate-pulse rounded-full bg-(--netz-brand-primary)/50"></div>
											</div>
											<span class="text-xs text-(--netz-text-muted)">Generating...</span>
										</div>
									{/if}
								</div>
							{/if}

							<!-- Status pipeline visualization -->
							{#if currentStage >= 0 && item.status !== "failed"}
								<div class="mt-3 flex items-center gap-1">
									{#each PIPELINE_STAGES as stage, i (stage)}
										{@const isActive = i <= currentStage}
										{@const isCurrent = stage === item.status}
										<div class="flex items-center gap-1">
											<div
												class="h-1.5 w-8 rounded-full transition-colors"
												class:bg-(--netz-brand-primary)={isActive}
												class:bg-(--netz-surface-alt)={!isActive}
											></div>
											{#if isCurrent}
												<span class="text-[10px] font-medium uppercase tracking-wider text-(--netz-text-muted)">
													{stage.replace("_", " ")}
												</span>
											{/if}
										</div>
									{/each}
								</div>
							{/if}
						</div>

						<div class="ml-4 flex flex-wrap gap-2">
							<!-- Download for approved/published -->
							{#if item.status === "approved" || item.status === "published"}
								<ActionButton
									size="sm"
									variant="outline"
									onclick={() => downloadContent(item.id, item.title ?? item.content_type)}
									loading={downloadingId === item.id}
									loadingText="..."
								>
									Download PDF
								</ActionButton>
							{/if}

							<!-- Approve/Reject for draft/review status -->
							{#if item.status === "draft" || item.status === "review" || item.status === "ready"}
								<ActionButton
									size="sm"
									onclick={() => openApproveDialog(item)}
								>
									Approve
								</ActionButton>
								<ActionButton
									size="sm"
									variant="destructive"
									onclick={() => openRejectDialog(item)}
								>
									Reject
								</ActionButton>
							{/if}
						</div>
					</div>
				</Card>
			{/each}
		</div>
	{:else}
		<EmptyState
			title="No Content"
			message="Generate investment outlooks, flash reports, or manager spotlights."
		/>
	{/if}
</div>

<!-- Spotlight Fund Picker Dialog -->
<Dialog bind:open={showSpotlightPicker} title="Select Fund for Spotlight">
	<div class="space-y-4">
		{#if loadingFunds}
			<p class="text-sm text-(--netz-text-muted)">Loading funds...</p>
		{:else if funds.length === 0}
			<p class="text-sm text-(--netz-text-muted)">No funds available.</p>
		{:else}
			<FormField label="Fund" required>
				<Select
					bind:value={spotlightFundId}
					placeholder="Select a fund..."
					options={funds.map((f) => ({ value: f.id, label: f.name }))}
					searchable
				/>
			</FormField>
		{/if}

		<div class="flex justify-end gap-2 pt-2">
			<Button variant="outline" onclick={() => showSpotlightPicker = false}>Cancel</Button>
			<ActionButton
				onclick={triggerSpotlight}
				loading={generating}
				loadingText="Generating..."
				disabled={!spotlightFundId}
			>
				Generate Spotlight
			</ActionButton>
		</div>
	</div>
</Dialog>

<!-- Approve ConsequenceDialog -->
<ConsequenceDialog
	bind:open={showApproveDialog}
	title="Approve Content"
	impactSummary="This will approve the content for distribution. Approved content can be downloaded as PDF and shared with clients."
	requireRationale={true}
	rationaleLabel="Approval rationale"
	rationalePlaceholder="Provide the basis for approving this content (e.g., data verified, narrative aligned with IC view, compliance reviewed)."
	confirmLabel="Approve content"
	metadata={[
		{ label: "Content", value: targetContentTitle, emphasis: true },
		{ label: "Action", value: "Approve for distribution" },
	]}
	onConfirm={handleApprove}
	onCancel={() => { showApproveDialog = false; targetContentId = null; }}
/>

<!-- Reject ConsequenceDialog -->
<!-- TODO: Backend POST /content/{id}/reject endpoint does not exist yet.
     When implemented, it should accept { rationale: string } and transition
     status from draft/review to rejected. -->
<ConsequenceDialog
	bind:open={showRejectDialog}
	title="Reject Content"
	impactSummary="This will reject the content. It will not be available for distribution and a new version will need to be generated."
	destructive={true}
	requireRationale={true}
	rationaleLabel="Rejection rationale"
	rationalePlaceholder="Explain why this content is being rejected (e.g., inaccurate data, misaligned narrative, compliance issue)."
	confirmLabel="Reject content"
	metadata={[
		{ label: "Content", value: targetContentTitle, emphasis: true },
		{ label: "Action", value: "Reject" },
	]}
	onConfirm={handleReject}
	onCancel={() => { showRejectDialog = false; targetContentId = null; }}
/>
