<!--
  Allocation — strategic, tactical, and effective allocation management.
  Delegates to AllocationView (self-loading component with profile selector).
-->
<script lang="ts">
	import { PageHeader } from "@netz/ui";
	import AllocationView from "$lib/components/AllocationView.svelte";
</script>

<PageHeader title="Allocation" subtitle="Strategic targets, tactical tilts, and effective allocation across risk profiles" />

<div class="alloc-page">
	<AllocationView />
</div>

<style>
	.alloc-page {
		padding-bottom: var(--netz-space-stack-xl, 48px);
	}
</style>
