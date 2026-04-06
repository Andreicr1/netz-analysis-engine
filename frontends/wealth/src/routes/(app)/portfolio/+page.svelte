<!--
  Builder — Model portfolio list, universe management, and policy configuration.
  Sub-pills: Models | Universe | Policy (smaller, left-aligned, visual hierarchy).
  Full-width content below sub-pills, no card cramming.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { Button } from "@investintell/ui/components/ui/button";
	import Play from "lucide-svelte/icons/play";
	import BarChart2 from "lucide-svelte/icons/bar-chart-2";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import { goto } from "$app/navigation";

	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import UniversePanel from "$lib/components/portfolio/UniversePanel.svelte";
	import PolicyPanel from "$lib/components/portfolio/PolicyPanel.svelte";
	import ModelListPanel from "$lib/components/portfolio/ModelListPanel.svelte";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	let portfolios = $derived((data.portfolios ?? []) as ModelPortfolio[]);

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	workspace.setGetToken(getToken);

	$effect(() => {
		if (workspace.universe.length === 0 && !workspace.isLoadingUniverse) {
			workspace.loadUniverse();
		}
	});

	function handleConstruct() {
		workspace.constructPortfolio();
	}

	function handleStressNav() {
		workspace.activeModelTab = "stress";
		goto("/portfolio/model");
	}

	const subTabs = [
		{ value: "models", label: "Models" },
		{ value: "universe", label: "Universe" },
		{ value: "policy", label: "Policy" },
	] as const;
</script>

<svelte:head>
	<title>Portfolio Builder — InvestIntell</title>
</svelte:head>

<div class="bld-page">

	<!-- ── Sub-pill bar + Actions ── -->
	<div class="bld-toolbar">
		<div class="bld-sub-pills">
			{#each subTabs as tab (tab.value)}
				{@const active = workspace.activeBuilderTab === tab.value}
				<button
					type="button"
					class="bld-sub-pill"
					class:bld-sub-pill--active={active}
					onclick={() => workspace.activeBuilderTab = tab.value}
				>
					{tab.label}
				</button>
			{/each}
		</div>

		<div class="bld-actions">
			<Button
				size="sm"
				variant="outline"
				disabled={!workspace.portfolioId || workspace.isConstructing}
				onclick={handleConstruct}
				class="h-9 text-[13px]"
			>
				{#if workspace.isConstructing}
					<Loader2 class="mr-1.5 h-4 w-4 animate-spin" />
					Building...
				{:else}
					<Play class="mr-1.5 h-4 w-4" />
					Construct
				{/if}
			</Button>
			<Button
				size="sm"
				variant="outline"
				disabled={!workspace.portfolioId}
				onclick={handleStressNav}
				class="h-9 text-[13px]"
			>
				<BarChart2 class="mr-1.5 h-4 w-4" />
				Stress Test
			</Button>
		</div>
	</div>

	<!-- ── Content area ── -->
	<div class="bld-content">
		{#if workspace.activeBuilderTab === "models"}
			<ModelListPanel {portfolios} />
		{:else if workspace.activeBuilderTab === "universe"}
			<UniversePanel />
		{:else}
			<PolicyPanel />
		{/if}
	</div>
</div>

<style>
	.bld-page {
		height: 100%;
		display: flex;
		flex-direction: column;
		gap: 24px;
		overflow: hidden;
	}

	/* ── Toolbar: sub-pills + actions ── */
	.bld-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
	}

	.bld-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	/* ── Sub-pills (smaller visual hierarchy) ── */
	.bld-sub-pills {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.bld-sub-pill {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 8px 20px;
		border: 1px solid #3a3b44;
		border-radius: 36px;
		background: transparent;
		color: #a1a1aa;
		font-size: 14px;
		font-weight: 600;
		font-family: "Urbanist", sans-serif;
		cursor: pointer;
		white-space: nowrap;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
		letter-spacing: 0.02em;
	}

	.bld-sub-pill:hover {
		background: #22232a;
		border-color: #52525b;
		color: #fff;
	}

	.bld-sub-pill--active {
		background: #0177fb;
		border-color: transparent;
		color: #fff;
	}

	.bld-sub-pill--active:hover {
		background: #0166d9;
	}

	/* ── Content ── */
	.bld-content {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}
</style>
