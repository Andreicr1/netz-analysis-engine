<!--
  Content Production — trigger outlooks/flash reports/spotlights, approve, download.
  Enhanced: fund picker for spotlights, approval with self-prevention, PDF download,
  polling for generating status, failed status display.
-->
<script lang="ts">
	import { DataTable, StatusBadge, PageHeader, EmptyState, Button, Card, Dialog, formatDate } from "@netz/ui";
	import { ActionButton, FormField } from "@netz/ui";
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
	let approvingId = $state<string | null>(null);
	let downloadingId = $state<string | null>(null);
	let actionError = $state<string | null>(null);

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

	async function approveContent(contentId: string) {
		approvingId = contentId;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/content/${contentId}/approve`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Approval failed";
		} finally {
			approvingId = null;
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

	// ── Polling for generating items ──
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
</script>

<div class="space-y-6 p-6">
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
		<div class="rounded-md border border-[var(--netz-status-error)] bg-[var(--netz-status-error)]/10 p-3 text-sm text-[var(--netz-status-error)]">
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	{#if contentList.length > 0}
		<div class="space-y-3">
			{#each contentList as item (item.id)}
				<Card class="flex items-center justify-between p-4">
					<div class="flex-1">
						<div class="flex items-center gap-2">
							<p class="text-sm font-medium text-[var(--netz-text-primary)]">
								{item.title ?? item.content_type}
							</p>
							<StatusBadge status={item.status} type="default" resolve={resolveWealthStatus} />
						</div>
						<p class="mt-1 text-xs text-[var(--netz-text-muted)]">
							{item.content_type} &middot; {formatDate(item.created_at)}
						</p>
						{#if item.status === "failed" && item.error_message}
							<p class="mt-1 text-xs text-[var(--netz-status-error)]">{item.error_message}</p>
						{/if}
					</div>
					<div class="ml-4 flex gap-2">
						{#if item.status === "ready" || item.status === "approved"}
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
						{#if item.status === "ready"}
							<ActionButton
								size="sm"
								onclick={() => approveContent(item.id)}
								loading={approvingId === item.id}
								loadingText="Approving..."
							>
								Approve
							</ActionButton>
						{/if}
						{#if item.status === "generating"}
							<span class="text-xs text-[var(--netz-text-muted)]">Generating...</span>
						{/if}
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
			<p class="text-sm text-[var(--netz-text-muted)]">Loading funds...</p>
		{:else if funds.length === 0}
			<p class="text-sm text-[var(--netz-text-muted)]">No funds available.</p>
		{:else}
			<FormField label="Fund" required>
				<select
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
					bind:value={spotlightFundId}
				>
					<option value="">Select a fund...</option>
					{#each funds as fund}
						<option value={fund.id}>{fund.name}</option>
					{/each}
				</select>
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
