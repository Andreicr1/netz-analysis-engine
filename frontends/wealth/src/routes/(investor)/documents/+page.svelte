<!--
  Investor — Published documents for distribution.
-->
<script lang="ts">
	import { PageHeader, EmptyState, formatDate } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	type Document = {
		id: string;
		content_type: string;
		title: string | null;
		status: string;
		created_at: string;
	};

	let documents = $derived((data.documents ?? []) as Document[]);
	let downloadingId = $state<string | null>(null);

	async function downloadDocument(docId: string, title: string | null) {
		downloadingId = docId;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(`/content/${docId}/download`);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `${title ?? "document"}-${docId}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch {
			// silently fail — could add error state if needed
		} finally {
			downloadingId = null;
		}
	}
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
				<div class="flex items-center justify-between rounded-lg border border-(--netz-border) bg-(--netz-surface-elevated) p-5 shadow-sm">
					<div class="flex-1">
						<p class="font-medium text-(--netz-text-primary)">
							{doc.title ?? doc.content_type}
						</p>
						<p class="text-sm text-(--netz-text-muted)">
							{doc.content_type}
							&middot; {formatDate(doc.created_at)}
						</p>
					</div>
					<button
						onclick={() => downloadDocument(doc.id, doc.title)}
						disabled={downloadingId === doc.id}
						class="inline-flex h-9 items-center gap-2 rounded-md bg-(--netz-brand-primary) px-4 text-sm font-medium text-white transition-colors hover:opacity-90 disabled:opacity-50"
					>
						<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
							<polyline points="7 10 12 15 17 10" />
							<line x1="12" y1="15" x2="12" y2="3" />
						</svg>
						{downloadingId === doc.id ? "Downloading..." : "Download"}
					</button>
				</div>
			{/each}
		</div>
	{/if}
</div>
