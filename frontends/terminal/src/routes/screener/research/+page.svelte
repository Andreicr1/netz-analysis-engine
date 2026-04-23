<script lang="ts">
	import "@investintell/ui/styles/surfaces/screener";
	import { page } from "$app/state";
	import TerminalResearchShell from "@investintell/ii-terminal-core/components/research/terminal/TerminalResearchShell.svelte";

	type ResearchMode = "universe" | "fund" | "holdings";

	const initialFundId = $derived(page.url.searchParams.get("fund"));
	const initialMode = $derived.by(() => {
		const mode = page.url.searchParams.get("mode");
		if (mode === "fund" || mode === "holdings" || mode === "universe") return mode as ResearchMode;
		return initialFundId ? "fund" : "universe";
	});
</script>

<svelte:head>
	<title>Screener Research</title>
</svelte:head>

<div class="research-page">
	<TerminalResearchShell {initialFundId} {initialMode} />
</div>

<style>
	.research-page {
		width: 100%;
		height: 100%;
		min-height: 0;
		background: var(--terminal-bg-void);
	}
</style>
