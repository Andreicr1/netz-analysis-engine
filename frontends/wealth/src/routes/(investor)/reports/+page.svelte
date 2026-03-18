<!--
  Investor — Published reports: investment outlooks, flash reports, spotlights.
-->
<script lang="ts">
	import { PageHeader, EmptyState, PDFDownload, formatDate } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	type Report = {
		id: string;
		content_type: string;
		status: string;
		title: string | null;
		created_at: string;
	};

	let reports = $derived((data.reports ?? []) as Report[]);

	const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

	const typeLabels: Record<string, string> = {
		outlooks: "Investment Outlook",
		"flash-reports": "Flash Report",
		spotlights: "Manager Spotlight",
	};
</script>

<div class="mx-auto max-w-5xl space-y-6 p-6 md:p-10">
	<PageHeader title="Reports" />

	{#if reports.length === 0}
		<EmptyState
			title="No Published Reports"
			message="Investment reports will appear here when published."
		/>
	{:else}
		<div class="space-y-3">
			{#each reports as report (report.id)}
				<div class="flex items-center justify-between rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5 shadow-sm">
					<div>
						<p class="font-medium text-[var(--netz-text-primary)]">
							{report.title ?? typeLabels[report.content_type] ?? report.content_type}
						</p>
						<p class="text-sm text-[var(--netz-text-muted)]">
							{typeLabels[report.content_type] ?? report.content_type}
							&middot; {formatDate(report.created_at)}
						</p>
					</div>
					<PDFDownload
						url="{API_BASE}/content/{report.id}/download"
						filename="{report.content_type}-{report.id}.pdf"
						languages={["en", "pt"]}
					/>
				</div>
			{/each}
		</div>
	{/if}
</div>
