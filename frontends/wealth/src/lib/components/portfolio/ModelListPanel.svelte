<!--
  ModelListPanel — Clickable list of model portfolios in the sidebar.
  Selecting a model updates the global workspace state.
  Design: floating text on dark bg with subtle separators (Figma One X).
-->
<script lang="ts">
	import { StatusBadge, formatDateTime, EmptyState } from "@investintell/ui";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import { profileColor } from "$lib/types/model-portfolio";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { portfolioDisplayName } from "$lib/constants/blocks";

	let { portfolios }: { portfolios: ModelPortfolio[] } = $props();
</script>

{#if portfolios.length === 0}
	<div class="p-6">
		<EmptyState title="No model portfolios" message="Create a strategy to begin." />
	</div>
{:else}
	<ul class="list-none p-0 m-0">
		{#each portfolios as mp (mp.id)}
			{@const active = mp.id === workspace.portfolioId}
			<li>
				<button
					class="flex flex-col gap-1.5 w-full px-5 py-4 border-none text-left cursor-pointer transition-colors duration-100
						{active
							? 'bg-[#0177fb]/10 border-l-[3px] border-l-[#0177fb]'
							: 'hover:bg-white/[0.03] border-l-[3px] border-l-transparent'}"
					style="border-bottom: 1px solid #404249; font-family: var(--ii-font-sans);"
					onclick={() => workspace.selectPortfolio(mp)}
				>
					<div class="flex justify-between items-center">
						<span
							class="text-[11px] font-bold uppercase tracking-[0.06em]"
							style:color={profileColor(mp.profile)}
						>
							{portfolioDisplayName(mp.profile)}
						</span>
						<StatusBadge status={mp.status} />
					</div>

					<span class="text-[15px] font-semibold text-white">
						{portfolioDisplayName(mp.display_name)}
					</span>

					<div class="flex gap-2 text-[12px] text-[#85a0bd]">
						{#if mp.fund_selection_schema}
							<span>{mp.fund_selection_schema.funds.length} funds</span>
						{/if}
						{#if mp.benchmark_composite}
							<span>{mp.benchmark_composite}</span>
						{/if}
					</div>

					<span class="text-[11px] text-[#85a0bd]/70">
						{formatDateTime(mp.created_at)}
					</span>
				</button>
			</li>
		{/each}
	</ul>
{/if}
