<!--
  @component PipelineFunnel
  Renders deal pipeline as a funnel chart using FunnelChart from @netz/ui.
-->
<script lang="ts">
	import { FunnelChart, Card } from "@netz/ui";

	let { data }: { data: Record<string, unknown> } = $props();

	// Extract stage distribution from pipeline analytics
	let stages = $derived(() => {
		const dist = data.stage_distribution as Array<{ stage: string; count: number }> | undefined;
		if (!dist) return [];
		return dist.map((d) => ({ name: d.stage, value: d.count }));
	});
</script>

<Card class="p-4">
	<h3 class="mb-3 text-sm font-medium text-[var(--netz-text-secondary)]">Deal Pipeline</h3>
	{#if stages().length > 0}
		<FunnelChart data={stages()} height={280} />
	{:else}
		<p class="py-8 text-center text-sm text-[var(--netz-text-muted)]">No pipeline data</p>
	{/if}
</Card>
