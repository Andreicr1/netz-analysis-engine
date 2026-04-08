<!--
  LibraryActionBar — multi-select toolbar above the Library grid.

  Phase 6 of the Library frontend (spec §3.4 Fase 6). Renders only
  when at least one document is selected via the multi-select state.
  Surfaces the count, a "Clear" affordance, and the "Create Meeting
  Pack" action — gated on actor role per spec §2.7. Investors never
  see the create button.
-->
<script lang="ts">
	import Package from "lucide-svelte/icons/package";
	import X from "lucide-svelte/icons/x";
	import type { BundleBuilder } from "$lib/state/library/bundle-builder.svelte";

	interface Props {
		bundle: BundleBuilder;
		canCreateBundle: boolean;
		onOpenWizard: () => void;
	}

	let { bundle, canCreateBundle, onOpenWizard }: Props = $props();

	const count = $derived(bundle.state.selected.size);
</script>

{#if count > 0}
	<div class="action-bar" role="region" aria-label="Library multi-select">
		<button
			type="button"
			class="action-bar__clear"
			onclick={() => bundle.clearSelection()}
			title="Clear selection"
			aria-label="Clear selection"
		>
			<X size={14} />
		</button>
		<span class="action-bar__count">
			{count} document{count === 1 ? "" : "s"} selected
		</span>

		{#if canCreateBundle}
			<button
				type="button"
				class="action-bar__primary"
				onclick={onOpenWizard}
			>
				<Package size={14} />
				Create Meeting Pack
			</button>
		{:else}
			<span class="action-bar__locked" title="IC role required">
				Meeting Pack — IC role required
			</span>
		{/if}
	</div>
{/if}

<style>
	.action-bar {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 10px 20px;
		background: color-mix(in srgb, #0177fb 14%, #141519);
		border-bottom: 1px solid #0177fb;
		color: #ffffff;
		font-family: var(--ii-font-sans, "Urbanist", system-ui, sans-serif);
		font-size: 13px;
	}

	.action-bar__clear {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		border: none;
		background: rgba(255, 255, 255, 0.12);
		color: #ffffff;
		border-radius: 999px;
		cursor: pointer;
	}

	.action-bar__clear:hover {
		background: rgba(255, 255, 255, 0.24);
	}

	.action-bar__count {
		font-weight: 600;
	}

	.action-bar__primary {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		margin-left: auto;
		padding: 6px 14px;
		border: 1px solid #0177fb;
		background: #0177fb;
		color: #ffffff;
		font-family: inherit;
		font-size: 12px;
		font-weight: 700;
		border-radius: 8px;
		cursor: pointer;
	}

	.action-bar__primary:hover {
		background: color-mix(in srgb, #0177fb 80%, #ffffff);
	}

	.action-bar__locked {
		margin-left: auto;
		font-size: 12px;
		color: #85a0bd;
	}
</style>
