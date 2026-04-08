<!--
  FilterRail — 260px sticky left rail for advanced filters on standalone
  analytical pages. Owns scrolling of filter groups; never scrolls the page.
  Caller composes filter UI via the `filters` snippet, optional `header` and
  `footer` snippets for branding / actions.
-->
<script lang="ts">
	import type { Snippet } from "svelte";

	interface Props {
		header?: Snippet;
		filters: Snippet;
		footer?: Snippet;
		width?: string;
	}

	let { header, filters, footer, width = "260px" }: Props = $props();
</script>

<aside class="fr-root" style:width aria-label="Filters">
	{#if header}
		<div class="fr-header">{@render header()}</div>
	{/if}
	<div class="fr-body">{@render filters()}</div>
	{#if footer}
		<div class="fr-footer">{@render footer()}</div>
	{/if}
</aside>

<style>
	.fr-root {
		flex-shrink: 0;
		height: 100%;
		min-height: 0;
		display: flex;
		flex-direction: column;
		background: var(--ii-surface-alt, #1a1c22);
		border-right: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.fr-header {
		padding: 16px 20px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		flex-shrink: 0;
	}
	.fr-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 16px 20px;
	}
	.fr-footer {
		padding: 12px 20px;
		border-top: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		flex-shrink: 0;
	}
</style>
