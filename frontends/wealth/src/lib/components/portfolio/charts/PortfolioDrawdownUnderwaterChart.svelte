<!--
  PortfolioDrawdownUnderwaterChart — Phase 6 Block B thin adapter that
  reuses Discovery's ``DrawdownUnderwaterChart`` for portfolio NAV.

  Same field-rename adapter pattern as PortfolioNavHeroChart. Discovery's
  chart already computes the underwater curve from raw nav points;
  this wrapper only adapts the field names.

  Per OD-26 — strict empty state when no NAV data.
-->
<script lang="ts">
	import { EmptyState } from "@investintell/ui";
	import DrawdownUnderwaterChart from "$lib/components/charts/discovery/DrawdownUnderwaterChart.svelte";
	import type { NAVPoint } from "$lib/types/model-portfolio";

	interface Props {
		navSeries: NAVPoint[];
		height?: number;
	}

	let { navSeries, height = 280 }: Props = $props();

	const adapted = $derived(
		navSeries.map((p) => ({
			nav_date: p.date,
			nav: p.nav,
			return_1d: p.daily_return,
		})),
	);

	const isEmpty = $derived(adapted.length === 0);
</script>

{#if isEmpty}
	<EmptyState
		title="No NAV history"
		message="Drawdown analysis requires a non-empty NAV series."
	/>
{:else}
	<DrawdownUnderwaterChart series={adapted} {height} />
{/if}
