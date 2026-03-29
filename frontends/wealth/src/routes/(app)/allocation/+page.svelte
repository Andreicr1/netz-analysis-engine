<!--
  Allocation — strategic, tactical, and effective allocation management.
  Delegates to AllocationView (self-loading component with profile selector).
-->
<script lang="ts">
	import { PageHeader } from "@investintell/ui";
	import AllocationView from "$lib/components/AllocationView.svelte";
</script>

<PageHeader title="Portfolio Allocation" subtitle="Review your base targets, active market adjustments, and final portfolio exposure." />

<div class="alloc-page">
	<AllocationView />
</div>

<style>
	.alloc-page {
		padding-bottom: var(--ii-space-stack-xl, 48px);
	}
</style>
