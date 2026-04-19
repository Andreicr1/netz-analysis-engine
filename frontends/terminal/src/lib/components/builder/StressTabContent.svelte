<!--
  X3.1 — STRESS tab content.

  Standalone stress-scenario surface. Reuses the wealth
  StressTab component (GFC / COVID / Taper / Rate Shock) but
  renders it as a full-height panel instead of a sub-tab of the
  portfolio builder. Portfolio selection is shared with the
  PORTFOLIO tab via the workspace singleton, so flipping between
  tabs keeps the current model selected.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { page } from "$app/state";
	import { workspace } from "@investintell/ii-terminal-core/state/portfolio-workspace.svelte";
	import type { ModelPortfolio } from "@investintell/ii-terminal-core/types/model-portfolio";
	import StressTab from "@investintell/ii-terminal-core/components/terminal/builder/StressTab.svelte";

	interface Props {
		portfolios: ModelPortfolio[];
	}

	let { portfolios }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	const urlPortfolioId = $derived(
		page.url.searchParams.get("portfolio_id"),
	);

	$effect(() => {
		workspace.setGetToken(getToken);
		const targetId = urlPortfolioId;
		const target = targetId
			? (portfolios.find((p) => p.id === targetId) ?? portfolios[0] ?? null)
			: (portfolios[0] ?? null);

		if (target && workspace.portfolio?.id !== target.id) {
			workspace.selectPortfolio(target);
		}
	});
</script>

<div class="stress">
	{#if portfolios.length === 0}
		<div class="stress__empty">
			No portfolios available — create one in PORTFOLIO tab first.
		</div>
	{:else}
		<StressTab />
	{/if}
</div>

<style>
	.stress {
		height: 100%;
		min-height: 0;
		overflow-y: auto;
		padding: var(--terminal-space-3);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-primary);
	}
	.stress__empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 200px;
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
	}
</style>
