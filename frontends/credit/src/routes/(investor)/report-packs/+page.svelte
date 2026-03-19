<!--
  Investor — Published report packs with PDF download.
-->
<script lang="ts">
	import { PageHeader, DataTable, EmptyState, PDFDownload, formatDate } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	let packs = $derived(data.packs ?? []);

	const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

	const columns = [
		{ accessorKey: "period_month", header: "Period" },
		{ accessorKey: "published_at", header: "Published" },
		{ accessorKey: "status", header: "Status" },
	];
</script>

<div class="p-6">
	<PageHeader title="Report Packs" />

	{#if !data.fundId}
		<EmptyState
			title="No Fund Selected"
			description="Select a fund to view report packs."
		/>
	{:else if packs.length === 0}
		<EmptyState
			title="No Report Packs"
			description="No published report packs available yet."
		/>
	{:else}
		<div class="mt-6 space-y-4">
			{#each packs as pack (pack.id)}
				<div class="flex items-center justify-between rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface)] p-4">
					<div>
						<p class="font-medium text-[var(--netz-text-primary)]">
							{pack.period_month ?? "Report Pack"}
						</p>
						{#if pack.published_at}
							<p class="text-sm text-[var(--netz-text-muted)]">
								Published: {formatDate(pack.published_at)}
							</p>
						{/if}
					</div>
					<PDFDownload
						url="{API_BASE}/funds/{data.fundId}/reports/monthly-pack/{pack.id}/download"
						filename="report-pack-{pack.period_month ?? pack.id}.pdf"
						languages={["en", "pt"]}
					/>
				</div>
			{/each}
		</div>
	{/if}
</div>
