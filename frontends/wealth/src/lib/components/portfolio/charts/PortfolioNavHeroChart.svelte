<!--
  PortfolioNavHeroChart — Phase 6 Block B thin adapter that reuses
  Discovery's ``NavHeroChart`` for portfolio NAV series.

  Discovery's NavHeroChart expects ``{nav_date, nav, return_1d}`` per
  point; the portfolio ``/track-record`` route returns
  ``{date, nav, daily_return}``. This adapter does the field-rename
  inline so the existing Discovery chart visual / tokens / tooltip
  formatter all work verbatim — no chart logic duplication.

  Per OD-26 — strict empty state when no NAV data.
-->
<script lang="ts">
	import { EmptyState } from "@investintell/ui";
	import NavHeroChart from "$wealth/components/charts/discovery/NavHeroChart.svelte";
	import type { NAVPoint } from "$wealth/types/model-portfolio";

	interface Props {
		navSeries: NAVPoint[];
		height?: number;
	}

	let { navSeries, height = 320 }: Props = $props();

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
		message="The portfolio's track-record endpoint returned no NAV series. Activate the portfolio or wait for the next nav synthesizer worker pass."
	/>
{:else}
	<NavHeroChart series={adapted} {height} />
{/if}
