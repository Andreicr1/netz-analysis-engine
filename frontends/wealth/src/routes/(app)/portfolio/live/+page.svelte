<!--
  /portfolio/live — Phase 8 Live Workbench (final major UI surface).

  Replaces the Phase 5 stub with the real monitoring dashboard.
  Filters the org's model portfolios down to ``state === "live"``
  and mounts the LiveWorkbenchShell (sidebar + KPIs + allocations
  table). The Phase 5 PortfolioSubNav ribbon is automatically
  visible because this route is under ``/portfolio/*`` and the
  portfolio layout mounts the ribbon unconditionally.

  URL state (DL15 — no localStorage):
    ?portfolio=<id>   — the currently-selected live portfolio

  When the query is missing or points to a non-live id, the shell
  falls back to the first portfolio in the list (auto-selected).
  Browser back/forward cycles through selection changes because
  the URL is the source of truth.

  Per CLAUDE.md: DL15 (no storage), DL16 (formatters), DL17 (no
  @tanstack/svelte-table — the allocations table is a plain
  semantic HTML table).

  Per the Phase 8 user mandate:
    - No ECharts
    - Reuse formatters from @investintell/ui
    - Extremely tight scope: visibility into active state, not
      building a trading execution system
-->
<script lang="ts">
	import { page } from "$app/state";
	import { goto } from "$app/navigation";
	import LiveWorkbenchShell from "$lib/components/portfolio/live/LiveWorkbenchShell.svelte";
	import type { PageData } from "./$types";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";

	let { data }: { data: PageData } = $props();

	// Filter down to live portfolios at the page level so the shell
	// stays pure — it never has to know about the "live" state check.
	const livePortfolios = $derived.by<ModelPortfolio[]>(() => {
		const rows = (data.portfolios ?? []) as ModelPortfolio[];
		return rows.filter((p) => p.state === "live");
	});

	// URL-derived selection. Falls back to the first live portfolio
	// if the query param is missing or stale.
	const selectedId = $derived<string | null>(
		page.url.searchParams.get("portfolio"),
	);

	async function handleSelect(portfolio: ModelPortfolio) {
		const url = new URL(page.url);
		url.searchParams.set("portfolio", portfolio.id);
		await goto(url, {
			replaceState: true,
			noScroll: true,
			keepFocus: true,
		});
	}
</script>

<svelte:head>
	<title>Live Workbench — InvestIntell</title>
</svelte:head>

<LiveWorkbenchShell
	portfolios={livePortfolios}
	{selectedId}
	onSelect={handleSelect}
/>
