<!--
  Neutral 3-column FCL primitive. Caller owns semantics via labels + ratios.
  State is caller-derived from URL — NEVER $bindable.
-->
<script lang="ts" module>
	export type FCLState = 'expand-1' | 'expand-2' | 'expand-3';
	export type FCLRatios = Record<FCLState, [number, number, number]>;

	export const DEFAULT_RATIOS: FCLRatios = {
		'expand-1': [1, 0, 0],
		'expand-2': [0.32, 0.68, 0],
		'expand-3': [0.22, 0.42, 0.36],
	};
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		state: FCLState;
		ratios?: Partial<FCLRatios>;
		column1?: Snippet;
		column2?: Snippet;
		column3?: Snippet;
		column1Label: string;
		column2Label: string;
		column3Label: string;
		overlayBreakpoint?: number;
	}

	let {
		state,
		ratios,
		column1,
		column2,
		column3,
		column1Label,
		column2Label,
		column3Label,
	}: Props = $props();

	const resolvedRatios = $derived<[number, number, number]>(
		ratios?.[state] ?? DEFAULT_RATIOS[state],
	);

	const gridTemplate = $derived(
		resolvedRatios.map((r) => (r === 0 ? '0fr' : `minmax(0, ${r}fr)`)).join(' '),
	);

	const col1Collapsed = $derived(resolvedRatios[0] === 0);
	const col2Collapsed = $derived(resolvedRatios[1] === 0);
	const col3Collapsed = $derived(resolvedRatios[2] === 0);
</script>

<div
	class="fcl-root"
	style:grid-template-columns={gridTemplate}
	data-state={state}
>
	<section
		class="fcl-col fcl-col-1"
		class:fcl-col--collapsed={col1Collapsed}
		aria-hidden={col1Collapsed}
		aria-label={column1Label}
	>
		{#if column1}{@render column1()}{/if}
	</section>
	<section
		class="fcl-col fcl-col-2"
		class:fcl-col--collapsed={col2Collapsed}
		aria-hidden={col2Collapsed}
		aria-label={column2Label}
	>
		{#if column2}{@render column2()}{/if}
	</section>
	<section
		class="fcl-col fcl-col-3"
		class:fcl-col--collapsed={col3Collapsed}
		aria-hidden={col3Collapsed}
		aria-label={column3Label}
	>
		{#if column3}{@render column3()}{/if}
	</section>
</div>

<style>
	.fcl-root {
		display: grid;
		width: 100%;
		height: 100%;
		min-height: 0;
		gap: 0;
		background: var(--ii-bg, #0e0f13);
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		transition: grid-template-columns 240ms cubic-bezier(0.4, 0, 0.2, 1);
		container-type: inline-size;
		container-name: fcl;
	}
	.fcl-col {
		min-width: 0;
		min-height: 0;
		overflow: auto;
		background: var(--ii-surface, #141519);
		position: relative;
	}
	.fcl-col-2,
	.fcl-col-3 {
		border-left: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
	}
	.fcl-col--collapsed {
		visibility: hidden;
		pointer-events: none;
		border: none;
	}
	@media (prefers-reduced-motion: reduce) {
		.fcl-root {
			transition: none;
		}
	}
	@container fcl (max-width: 1100px) {
		.fcl-root[data-state='expand-3'] {
			grid-template-columns: minmax(0, 2fr) minmax(0, 3fr) 0fr;
		}
		.fcl-root[data-state='expand-3'] .fcl-col-3 {
			position: absolute;
			top: 0;
			right: 0;
			bottom: 0;
			width: min(520px, 80%);
			visibility: visible;
			pointer-events: auto;
			border-left: 1px solid var(--ii-border-subtle);
			box-shadow: -12px 0 32px -16px rgb(0 0 0 / 0.4);
			z-index: 10;
		}
	}
</style>
