<!--
  Document review queue — DataTable of pending reviews.
-->
<script lang="ts">
	import { DataTable, DataCard, EmptyState, PageHeader } from "@netz/ui";
	import type { PageData } from "./$types";
	import type { PaginatedResponse, ReviewItem, ReviewSummary } from "$lib/types/api";

	let { data }: { data: PageData } = $props();

	let reviews = $derived((data.reviews as PaginatedResponse<ReviewItem>)?.items ?? []);
	let summary = $derived(data.summary as ReviewSummary | null);

	function humanizeEnum(value: string): string {
		return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}

	const columns = [
		{ accessorKey: "document_title", header: "Document" },
		{ accessorKey: "document_type", header: "Type", cell: (info: { getValue: () => string }) => humanizeEnum(info.getValue() ?? "") },
		{ accessorKey: "status", header: "Status", cell: (info: { getValue: () => string }) => humanizeEnum(info.getValue() ?? "") },
		{ accessorKey: "priority", header: "Priority", cell: (info: { getValue: () => string }) => humanizeEnum(info.getValue() ?? "") },
		{ accessorKey: "created_at", header: "Submitted" },
	];
</script>

<div class="px-6">
	<PageHeader
		title="Document Reviews"
		breadcrumbs={[{ label: "Funds", href: "/funds" }, { label: "Documents", href: `/funds/${data.fundId}/documents` }, { label: "Reviews" }]}
	/>

	{#if summary}
		<div class="mb-6 grid gap-4 md:grid-cols-4">
			<DataCard label="Pending" value={String(summary.pending ?? 0)} trend="flat" />
			<DataCard label="Under Review" value={String(summary.under_review ?? 0)} trend="flat" />
			<DataCard label="Approved" value={String(summary.approved ?? 0)} trend="up" />
			<DataCard label="Rejected" value={String(summary.rejected ?? 0)} trend="flat" />
		</div>
	{/if}

	{#if reviews.length === 0}
		<EmptyState title="No Reviews" description="Document reviews will appear here." />
	{:else}
		<DataTable data={reviews} {columns} />
	{/if}
</div>
