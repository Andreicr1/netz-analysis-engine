<!--
  /portfolio/live — Phase 2 Terminal Grid Shell.

  Owns the URL-derived portfolio selection and hands it to the shell
  as pure props. The old tool state machine (overview, drift_analysis,
  execution_desk) was removed — the terminal grid is a fixed 4-zone
  layout with no tab switching.

  URL state (DL15 — Zero localStorage):
    ?portfolio=<id>   — the currently-selected live portfolio
-->
<script lang="ts">
	import { page } from "$app/state";
	import { goto } from "$app/navigation";
	import { resolve } from "$app/paths";
	import LiveWorkbenchShell from "$lib/components/portfolio/live/LiveWorkbenchShell.svelte";
	import type { PageData } from "./$types";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";

	let { data }: { data: PageData } = $props();

	const livePortfolios = $derived.by<ModelPortfolio[]>(() => {
		const rows = (data.portfolios ?? []) as ModelPortfolio[];
		return rows;
	});

	const selectedId = $derived<string | null>(
		page.url.searchParams.get("portfolio"),
	);

	const initialMode = $derived<"LIVE" | "EDIT">(
		page.url.searchParams.get("mode") === "edit" ? "EDIT" : "LIVE",
	);

	async function handleSelect(portfolio: ModelPortfolio) {
		const params = new URLSearchParams(page.url.searchParams);
		params.set("portfolio", portfolio.id);
		const target = resolve(`/portfolio/live?${params.toString()}`);
		await goto(target, {
			replaceState: true,
			noScroll: true,
			keepFocus: true,
		});
	}
</script>

<svelte:head>
	<title>Terminal — InvestIntell</title>
</svelte:head>

<LiveWorkbenchShell
	portfolios={livePortfolios}
	{selectedId}
	{initialMode}
	onSelect={handleSelect}
/>
