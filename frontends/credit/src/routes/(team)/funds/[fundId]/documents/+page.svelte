<!--
  Document list with DataTable, filterable by root_folder and domain.
-->
<script lang="ts">
	import { DataTable, Button, EmptyState, PageTabs } from "@netz/ui";
	import type { PageData } from "./$types";
	import type { PaginatedResponse, DocumentItem } from "$lib/types/api";

	let { data }: { data: PageData } = $props();
	let activeTab = $state("all");

	let documents = $derived((data.documents as PaginatedResponse<DocumentItem>)?.items ?? []);

	const columns = [
		{ accessorKey: "title", header: "Title" },
		{ accessorKey: "root_folder", header: "Folder" },
		{ accessorKey: "domain", header: "Domain" },
		{ accessorKey: "status", header: "Status" },
		{ accessorKey: "created_at", header: "Uploaded" },
	];
</script>

<div class="p-6">
	<div class="mb-4 flex items-center justify-between">
		<h2 class="text-xl font-semibold text-[var(--netz-text-primary)]">Documents</h2>
		<div class="flex gap-2">
			<Button href="/funds/{data.fundId}/documents/upload">Upload</Button>
			<Button href="/funds/{data.fundId}/documents/reviews" variant="outline">Reviews</Button>
			<Button href="/funds/{data.fundId}/documents/dataroom" variant="outline">Dataroom</Button>
		</div>
	</div>

	{#if documents.length === 0}
		<EmptyState
			title="No Documents"
			description="Upload documents to start the ingestion pipeline."
		/>
	{:else}
		<DataTable data={documents} {columns} />
	{/if}
</div>
