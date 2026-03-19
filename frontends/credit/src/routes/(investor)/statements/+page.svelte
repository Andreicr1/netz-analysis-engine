<!--
  Investor — Published statements with download.
-->
<script lang="ts">
	import { PageHeader, EmptyState, PDFDownload, formatDate } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	let statements = $derived(data.statements ?? []);

	const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
</script>

<div class="p-6">
	<PageHeader title="Investor Statements" />

	{#if !data.fundId}
		<EmptyState
			title="No Fund Selected"
			description="Select a fund to view statements."
		/>
	{:else if statements.length === 0}
		<EmptyState
			title="No Statements"
			description="No investor statements available yet."
		/>
	{:else}
		<div class="mt-6 space-y-4">
			{#each statements as stmt (stmt.id)}
				<div class="flex items-center justify-between rounded-lg border border-(--netz-border) bg-(--netz-surface) p-4">
					<div>
						<p class="font-medium text-(--netz-text-primary)">
							{stmt.period_month ?? "Statement"}
						</p>
						{#if stmt.created_at}
							<p class="text-sm text-(--netz-text-muted)">
								Issued: {formatDate(stmt.created_at as string)}
							</p>
						{/if}
					</div>
					<PDFDownload
						url="{API_BASE}/funds/{data.fundId}/reports/investor-statements/{stmt.id}/download"
						filename="statement-{stmt.period_month ?? stmt.id}.json"
						languages={["en", "pt"]}
					/>
				</div>
			{/each}
		</div>
	{/if}
</div>
