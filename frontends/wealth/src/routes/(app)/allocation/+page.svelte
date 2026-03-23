<!--
  Allocation — strategic, tactical, and effective allocation management.
  Delegates to AllocationView (self-loading component with profile selector).
-->
<script lang="ts">
	import { PageHeader } from "@netz/ui";
	import AllocationView from "$lib/components/AllocationView.svelte";
</script>

<PageHeader
	title="Allocation"
	breadcrumbs={[{ label: "Allocation" }]}
/>

<div class="alloc-page">
	<AllocationView />
</div>

<style>
	.alloc-page {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
	}
</style>
