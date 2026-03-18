<!--
  Investor — Published fact-sheets with PDF download, generation trigger, and language toggle.
-->
<script lang="ts">
	import { PageHeader, EmptyState, Card, Button, formatDate } from "@netz/ui";
	import { ActionButton } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	type FactSheet = {
		path: string;
		portfolio_name: string;
		portfolio_id: string;
		period: string | null;
		created_at: string | null;
		format: string | null;
	};

	let factSheets = $derived((data.factSheets ?? []) as FactSheet[]);
	let generatingId = $state<string | null>(null);
	let downloadingPath = $state<string | null>(null);
	let actionError = $state<string | null>(null);

	async function generateFactSheet(portfolioId: string) {
		generatingId = portfolioId;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/fact-sheets/model-portfolios/${portfolioId}`, {}, { timeoutMs: 30_000 });
			await invalidateAll();
		} catch (e) {
			if (e instanceof Error && e.message.includes("timeout")) {
				actionError = "Server busy, please try again in a moment.";
			} else {
				actionError = e instanceof Error ? e.message : "Generation failed";
			}
		} finally {
			generatingId = null;
		}
	}

	async function downloadFactSheet(path: string, name: string) {
		downloadingPath = path;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(`/fact-sheets/${encodeURIComponent(path)}/download`);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `fact-sheet-${name.toLowerCase().replace(/\s+/g, "-")}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloadingPath = null;
		}
	}
</script>

<div class="mx-auto max-w-5xl space-y-6 p-6 md:p-10">
	<PageHeader title="Fact Sheets" />

	{#if actionError}
		<div class="rounded-md border border-[var(--netz-status-error)] bg-[var(--netz-status-error)]/10 p-3 text-sm text-[var(--netz-status-error)]">
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	{#if factSheets.length === 0}
		<EmptyState
			title="No Fact Sheets"
			message="Published fact-sheets will appear here when available."
		/>
	{:else}
		<div class="space-y-3">
			{#each factSheets as fs (fs.path)}
				<Card class="flex items-center justify-between p-5">
					<div>
						<p class="font-medium text-[var(--netz-text-primary)]">
							{fs.portfolio_name}
						</p>
						<p class="text-sm text-[var(--netz-text-muted)]">
							{fs.format ?? "Fact Sheet"}
							{#if fs.period}
								&middot; {fs.period}
							{/if}
							{#if fs.created_at}
								&middot; {formatDate(fs.created_at)}
							{/if}
						</p>
					</div>
					<div class="flex gap-2">
						<ActionButton
							size="sm"
							variant="outline"
							onclick={() => downloadFactSheet(fs.path, fs.portfolio_name)}
							loading={downloadingPath === fs.path}
							loadingText="..."
						>
							Download PDF
						</ActionButton>
						<ActionButton
							size="sm"
							onclick={() => generateFactSheet(fs.portfolio_id)}
							loading={generatingId === fs.portfolio_id}
							loadingText="Generating..."
						>
							Regenerate
						</ActionButton>
					</div>
				</Card>
			{/each}
		</div>
	{/if}
</div>
