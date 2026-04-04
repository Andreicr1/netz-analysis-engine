<!--
  Allocation — strategic, tactical, and effective allocation management.
  SSR-loaded; AllocationView receives data as props, profile switch via goto.
-->
<script lang="ts">
	import { PageHeader } from "@investintell/ui";
	import AllocationView from "$lib/components/AllocationView.svelte";

	let { data } = $props();
</script>

<PageHeader title="Portfolio Allocation" subtitle="Review your base targets, active market adjustments, and final portfolio exposure." />

<div class="alloc-page">
	<AllocationView
		blocks={data.blocks}
		strategic={data.strategic}
		tactical={data.tactical}
		effective={data.effective}
		profile={data.profile}
	/>
</div>

<style>
	.alloc-page {
		padding-bottom: var(--ii-space-stack-xl, 48px);
	}
</style>
