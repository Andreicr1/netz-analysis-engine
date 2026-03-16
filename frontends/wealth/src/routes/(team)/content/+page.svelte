<!--
  Content Production — trigger outlooks/flash reports/spotlights, approve, download.
-->
<script lang="ts">
	import { DataTable, StatusBadge, PageHeader, EmptyState, Button, PDFDownload } from "@netz/ui";
	import type { PageData } from "./$types";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";

	let { data }: { data: PageData } = $props();

	type ContentSummary = {
		id: string;
		content_type: string;
		status: string;
		created_at: string;
		title: string | null;
	};

	let contentList = $derived((data.content ?? []) as ContentSummary[]);

	let generating = $state(false);

	const columns = [
		{ accessorKey: "title", header: "Title" },
		{ accessorKey: "content_type", header: "Type" },
		{ accessorKey: "status", header: "Status" },
		{
			accessorKey: "created_at",
			header: "Created",
			cell: (info: { getValue: () => unknown }) =>
				new Date(info.getValue() as string).toLocaleDateString(),
		},
	];

	async function triggerGeneration(type: string) {
		generating = true;
		try {
			const api = createClientApiClient(async () => "dev-token");
			await api.post(`/content/${type}`, {});
			await invalidateAll();
		} catch {
			// Handled by api-client
		} finally {
			generating = false;
		}
	}

	async function approveContent(contentId: string) {
		try {
			const api = createClientApiClient(async () => "dev-token");
			await api.post(`/content/${contentId}/approve`, {});
			await invalidateAll();
		} catch {
			// Handled by api-client (409 for self-approval blocked)
		}
	}
</script>

<div class="space-y-6 p-6">
	<PageHeader title="Content Production">
		{#snippet actions()}
			<div class="flex gap-2">
				<Button onclick={() => triggerGeneration("outlooks")} disabled={generating}>
					Generate Outlook
				</Button>
				<Button onclick={() => triggerGeneration("flash-reports")} disabled={generating}>
					Flash Report
				</Button>
				<Button onclick={() => triggerGeneration("spotlights")} disabled={generating}>
					Spotlight
				</Button>
			</div>
		{/snippet}
	</PageHeader>

	{#if contentList.length > 0}
		<DataTable data={contentList} {columns} />
	{:else}
		<EmptyState
			title="No Content"
			message="Generate investment outlooks, flash reports, or manager spotlights."
		/>
	{/if}
</div>
