<!--
  Investor — Published fact-sheets with PDF download and language toggle.
-->
<script lang="ts">
	import { PageHeader, EmptyState, PDFDownload } from "@netz/ui";
	import type { PageData } from "./$types";

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

	const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
</script>

<div class="mx-auto max-w-5xl space-y-6 p-6 md:p-10">
	<PageHeader title="Fact Sheets" />

	{#if factSheets.length === 0}
		<EmptyState
			title="No Fact Sheets"
			message="Published fact-sheets will appear here when available."
		/>
	{:else}
		<div class="space-y-3">
			{#each factSheets as fs (fs.path)}
				<div class="flex items-center justify-between rounded-lg border border-[var(--netz-border)] bg-white p-5 shadow-sm">
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
								&middot; {new Date(fs.created_at).toLocaleDateString()}
							{/if}
						</p>
					</div>
					<PDFDownload
						url="{API_BASE}/fact-sheets/{encodeURIComponent(fs.path)}/download"
						filename="fact-sheet-{fs.portfolio_name.toLowerCase().replace(/\s+/g, '-')}.pdf"
						languages={["en", "pt"]}
					/>
				</div>
			{/each}
		</div>
	{/if}
</div>
