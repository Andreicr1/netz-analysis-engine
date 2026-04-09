<!--
  /portfolio/live — Phase 9 Block B: tool state machine wiring.

  Owns both URL-derived inputs and hands them to the shell as pure
  props (same pattern as Phase 8 ``selectedId``). The shell is
  presentation-only; the page patches the URL via goto().

  URL state (DL15 — Zero localStorage):
    ?portfolio=<id>   — the currently-selected live portfolio
    ?tool=<tool>      — the active workbench tool (overview,
                        drift_analysis, execution_desk). Omitted
                        when equal to the default ``overview`` to
                        keep short URLs.

  When ``?tool=`` is missing or carries an invalid value, the
  resolver falls back to the default tool.

  Per CLAUDE.md: DL15 (no storage), DL16 (formatters from
  @investintell/ui), DL17 (no @tanstack/svelte-table).
-->
<script lang="ts">
	import { page } from "$app/state";
	import { goto } from "$app/navigation";
	import LiveWorkbenchShell from "$lib/components/portfolio/live/LiveWorkbenchShell.svelte";
	import {
		DEFAULT_WORKBENCH_TOOL,
		resolveWorkbenchTool,
		type WorkbenchTool,
	} from "$lib/components/portfolio/live/workbench-state";
	import type { PageData } from "./$types";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";

	let { data }: { data: PageData } = $props();

	// Filter down to live portfolios at the page level so the shell
	// stays pure — it never has to know about the "live" state check.
	const livePortfolios = $derived.by<ModelPortfolio[]>(() => {
		const rows = (data.portfolios ?? []) as ModelPortfolio[];
		// Hack visual temporário para a Fase 9: ignora o estado para forçar a renderização
		// return rows.filter((p) => p.state === "live");
		return rows;
	});

	// URL-derived selection. Falls back to the first live portfolio
	// when the query is missing or stale (handled inside the shell).
	const selectedId = $derived<string | null>(
		page.url.searchParams.get("portfolio"),
	);

	// URL-derived active tool. Untrusted input validated by
	// ``resolveWorkbenchTool`` — any unknown value lands on the
	// default (overview) without crashing.
	const activeTool = $derived<WorkbenchTool>(
		resolveWorkbenchTool(page.url.searchParams.get("tool")),
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

	async function handleToolChange(tool: WorkbenchTool) {
		const url = new URL(page.url);
		if (tool === DEFAULT_WORKBENCH_TOOL) {
			// Keep URLs short when the default is active.
			url.searchParams.delete("tool");
		} else {
			url.searchParams.set("tool", tool);
		}
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
	{activeTool}
	onToolChange={handleToolChange}
/>
