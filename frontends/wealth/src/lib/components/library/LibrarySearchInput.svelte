<!--
  LibrarySearchInput — debounced full-text search field.

  Phase 4 of the Library frontend (spec §3.4 Fase 4). Mirrors the
  current value of `adapter.state.q` so that browser back/forward
  or a copy-pasted URL paint the input correctly. Calls
  `adapter.setQuery(value, { debounce: true })` on input so the URL
  push waits 300 ms after the last keystroke per spec.

  The component is intentionally just an input — the search results
  list lives elsewhere (Phase 5 / future). All filter chips push
  immediately; only the typing path is debounced.
-->
<script lang="ts">
	import Search from "lucide-svelte/icons/search";
	import X from "lucide-svelte/icons/x";
	import type { UrlAdapter } from "$wealth/state/library/url-adapter.svelte";

	interface Props {
		adapter: UrlAdapter;
	}

	let { adapter }: Props = $props();

	function handleInput(event: Event): void {
		const value = (event.currentTarget as HTMLInputElement).value;
		adapter.setQuery(value, { debounce: true });
	}

	function clear(): void {
		adapter.setQuery("");
	}
</script>

<div class="search">
	<span class="search__icon" aria-hidden="true">
		<Search size={14} />
	</span>
	<input
		type="search"
		class="search__input"
		placeholder="Search the Library..."
		aria-label="Search the Library"
		value={adapter.state.q}
		oninput={handleInput}
	/>
	{#if adapter.state.q}
		<button
			type="button"
			class="search__clear"
			aria-label="Clear search"
			onclick={clear}
		>
			<X size={12} />
		</button>
	{/if}
</div>

<style>
	.search {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 10px;
		background: #1d1f25;
		border: 1px solid #404249;
		border-radius: 8px;
		color: #cbccd1;
		font-family: var(--ii-font-sans, "Urbanist", system-ui, sans-serif);
		min-width: 240px;
		max-width: 380px;
		flex: 1;
		transition: border-color 120ms ease;
	}

	.search:focus-within {
		border-color: #0177fb;
	}

	.search__icon {
		display: inline-flex;
		align-items: center;
		color: #85a0bd;
	}

	.search__input {
		flex: 1;
		min-width: 0;
		background: transparent;
		border: none;
		outline: none;
		color: #ffffff;
		font: inherit;
		font-size: 13px;
	}

	.search__input::placeholder {
		color: #85a0bd;
	}

	.search__clear {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 18px;
		height: 18px;
		border: none;
		background: #404249;
		color: #cbccd1;
		border-radius: 999px;
		cursor: pointer;
	}

	.search__clear:hover {
		background: #0177fb;
		color: #ffffff;
	}
</style>
