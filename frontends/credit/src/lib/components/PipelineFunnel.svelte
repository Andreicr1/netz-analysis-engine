<!--
  @component PipelineFunnel
  Renders deal pipeline as a funnel chart using FunnelChart from @netz/ui.
-->
<script lang="ts">
	import { FunnelChart, Card } from "@netz/ui";
	import type { PipelineAnalytics } from "$lib/types/api";

	let { data }: { data: PipelineAnalytics } = $props();

	// Extract stage distribution from pipeline analytics
	let funnelStages = $derived.by(() => {
		const dist = data.stages;
		if (!dist) return [];
		return dist.map((d) => ({ name: d.stage, value: d.count }));
	});
</script>

<Card class="p-4">
	<h3 class="mb-3 text-sm font-medium text-(--netz-text-secondary)">Deal Pipeline</h3>
	{#if funnelStages.length > 0}
		<FunnelChart stages={funnelStages} height={280} />
	{:else}
		<p class="py-8 text-center text-sm text-(--netz-text-muted)">No pipeline data</p>
	{/if}
</Card>
