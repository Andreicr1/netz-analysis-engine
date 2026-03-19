<!--
  Investor — Approved-for-distribution documents.
-->
<script lang="ts">
	import { PageHeader, EmptyState, StatusBadge, formatDate } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	let documents = $derived(data.documents ?? []);

	const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

	function downloadDocument(doc: Record<string, unknown>) {
		if (doc.blob_uri) {
			window.open(`${API_BASE}/documents/${doc.id}/download`, "_blank");
		}
	}
</script>

<div class="p-6">
	<PageHeader title="Documents" />

	{#if !data.fundId}
		<EmptyState
			title="No Fund Selected"
			description="Select a fund to view documents."
		/>
	{:else if documents.length === 0}
		<EmptyState
			title="No Documents"
			description="No approved documents available yet."
		/>
	{:else}
		<div class="mt-6 space-y-3">
			{#each documents as doc (doc.id)}
				<div class="flex items-center justify-between rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface)] p-4">
					<div class="flex-1">
						<div class="flex items-center gap-2">
							<p class="font-medium text-[var(--netz-text-primary)]">
								{doc.title}
							</p>
							<StatusBadge status={doc.status as string} />
						</div>
						<p class="mt-1 text-sm text-[var(--netz-text-muted)]">
							{doc.document_type}
							{#if doc.created_at}
								&middot; {formatDate(doc.created_at as string)}
							{/if}
						</p>
					</div>
					{#if doc.blob_uri}
						<button
							class="inline-flex h-9 items-center gap-2 rounded-md bg-[var(--netz-brand-primary)] px-4 text-sm font-medium text-white transition-colors hover:opacity-90"
							onclick={() => downloadDocument(doc)}
						>
							<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
								<polyline points="7 10 12 15 17 10" />
								<line x1="12" y1="15" x2="12" y2="3" />
							</svg>
							Download
						</button>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
