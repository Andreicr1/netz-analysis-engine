<!--
  Investor — Published documents for distribution.
-->
<script lang="ts">
	import { PageHeader, EmptyState } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	type Document = {
		id: string;
		content_type: string;
		title: string | null;
		status: string;
		created_at: string;
	};

	let documents = $derived((data.documents ?? []) as Document[]);

	const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
</script>

<div class="mx-auto max-w-5xl space-y-6 p-6 md:p-10">
	<PageHeader title="Documents" />

	{#if documents.length === 0}
		<EmptyState
			title="No Documents"
			message="Published documents will appear here when available."
		/>
	{:else}
		<div class="space-y-3">
			{#each documents as doc (doc.id)}
				<div class="flex items-center justify-between rounded-lg border border-[var(--netz-border)] bg-white p-5 shadow-sm">
					<div class="flex-1">
						<p class="font-medium text-[var(--netz-text-primary)]">
							{doc.title ?? doc.content_type}
						</p>
						<p class="text-sm text-[var(--netz-text-muted)]">
							{doc.content_type}
							&middot; {new Date(doc.created_at).toLocaleDateString()}
						</p>
					</div>
					<a
						href="{API_BASE}/content/{doc.id}/download"
						target="_blank"
						rel="noopener"
						class="inline-flex h-9 items-center gap-2 rounded-md bg-[var(--netz-brand-primary,var(--netz-primary))] px-4 text-sm font-medium text-white transition-colors hover:opacity-90"
					>
						<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
							<polyline points="7 10 12 15 17 10" />
							<line x1="12" y1="15" x2="12" y2="3" />
						</svg>
						Download
					</a>
				</div>
			{/each}
		</div>
	{/if}
</div>
