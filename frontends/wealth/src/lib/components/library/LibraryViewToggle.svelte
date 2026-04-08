<!--
  LibraryViewToggle — Tree / List / Grid switch.

  Phase 4 of the Library frontend (spec §3.4 Fase 4). Writes the
  selected view mode through the URL adapter so it round-trips with
  every other piece of Library state. The actual List/Grid rendering
  arrives in a follow-up sprint — for now the LibraryShell renders
  structural placeholders for those modes so the URL contract is
  already correct end-to-end.
-->
<script lang="ts">
	import LayoutGrid from "lucide-svelte/icons/layout-grid";
	import List from "lucide-svelte/icons/list";
	import Network from "lucide-svelte/icons/network";
	import type {
		LibraryViewMode,
		UrlAdapter,
	} from "$lib/state/library/url-adapter.svelte";

	interface Props {
		adapter: UrlAdapter;
	}

	let { adapter }: Props = $props();

	const OPTIONS: Array<{
		value: LibraryViewMode;
		label: string;
		icon: typeof Network;
	}> = [
		{ value: "tree", label: "Tree", icon: Network },
		{ value: "list", label: "List", icon: List },
		{ value: "grid", label: "Grid", icon: LayoutGrid },
	];
</script>

<div class="toggle" role="group" aria-label="Library view">
	{#each OPTIONS as option (option.value)}
		{@const Icon = option.icon}
		<button
			type="button"
			class="toggle__btn"
			class:toggle__btn--active={adapter.state.view === option.value}
			aria-pressed={adapter.state.view === option.value}
			title={option.label}
			onclick={() => adapter.setView(option.value)}
		>
			<Icon size={14} />
			<span class="toggle__label">{option.label}</span>
		</button>
	{/each}
</div>

<style>
	.toggle {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		padding: 3px;
		background: #1d1f25;
		border: 1px solid #404249;
		border-radius: 8px;
		font-family: var(--ii-font-sans, "Urbanist", system-ui, sans-serif);
	}

	.toggle__btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 5px 10px;
		border: none;
		background: transparent;
		color: #85a0bd;
		font-family: inherit;
		font-size: 12px;
		font-weight: 600;
		border-radius: 6px;
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.toggle__btn:hover {
		color: #ffffff;
	}

	.toggle__btn--active {
		background: color-mix(in srgb, #0177fb 22%, #141519);
		color: #ffffff;
	}

	.toggle__label {
		font-size: 12px;
	}
</style>
