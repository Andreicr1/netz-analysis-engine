<!--
  WorkbenchLayout — high-density terminal shell primitive.

  Neutral 2-column workbench primitive promoted from the Phase 8
  bespoke LiveWorkbenchShell layout. This is NOT FlexibleColumnLayout
  — FCL is a 3-column resizable deep-dive surface. The Workbench is
  a fixed-sidebar monitoring + execution surface where the left rail
  width is pinned, the main area flexes, and the header row carries
  a persistent tool ribbon (see Wealth /portfolio/live).

  Layout:

    ┌── sidebar ─┐ ┌──────── header ─────────┐
    │            │ ├──────────────────────────┤
    │            │ │          main            │
    └────────────┘ └──────────────────────────┘

  Caller owns:
    - sidebar snippet (portfolio list, instrument list, etc.)
    - header snippet (title + WorkbenchToolRibbon + status chips)
    - main   snippet (active tool surface)
    - sidebarWidth (default 280px — tune per vertical)

  Design rules:
    - No $bindable state. All state is caller-derived from URL
      per DL15 (Zero localStorage). The primitive is pure
      presentation.
    - 2-column grid with fixed sidebar, minmax(0, 1fr) main area
      so the main column can shrink without overflowing the parent
      content panel (matches the Phase 8 container-query pattern).
    - Height fills the parent — the portfolio/+layout.svelte layout
      cage (calc(100vh - 88px) + padding: 24px) is the authoritative
      outer box, not this primitive.
-->
<script lang="ts" module>
	export type WorkbenchLayoutSidebarWidth = string;
</script>

<script lang="ts">
	import type { Snippet } from "svelte";

	interface Props {
		sidebar?: Snippet;
		header?: Snippet;
		main?: Snippet;
		/** CSS length for the fixed left rail. Defaults to 280px. */
		sidebarWidth?: WorkbenchLayoutSidebarWidth;
		sidebarLabel?: string;
		headerLabel?: string;
		mainLabel?: string;
	}

	let {
		sidebar,
		header,
		main,
		sidebarWidth = "280px",
		sidebarLabel = "Workbench sidebar",
		headerLabel = "Workbench header",
		mainLabel = "Workbench main",
	}: Props = $props();

	const rootStyle = $derived(
		`grid-template-columns: ${sidebarWidth} minmax(0, 1fr);`,
	);
</script>

<div class="wb-root" style={rootStyle} data-density="workbench">
	<aside class="wb-sidebar" aria-label={sidebarLabel}>
		{#if sidebar}{@render sidebar()}{/if}
	</aside>

	<div class="wb-main-area">
		{#if header}
			<div class="wb-header" role="toolbar" aria-label={headerLabel}>
				{@render header()}
			</div>
		{/if}
		<main class="wb-main" aria-label={mainLabel}>
			{#if main}{@render main()}{/if}
		</main>
	</div>
</div>

<style>
	.wb-root {
		display: grid;
		width: 100%;
		height: 100%;
		min-height: 0;
		background: var(--ii-bg, #0e0f13);
		font-family: "Urbanist", system-ui, sans-serif;
		container-type: inline-size;
		container-name: workbench;
	}

	.wb-sidebar {
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		display: flex;
		flex-direction: column;
		background: var(--ii-surface, #141519);
		border-right: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
	}

	.wb-main-area {
		display: grid;
		grid-template-rows: auto minmax(0, 1fr);
		min-width: 0;
		min-height: 0;
		background: var(--ii-bg, #0e0f13);
	}

	.wb-header {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 16px 24px 12px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		flex-shrink: 0;
		min-width: 0;
	}

	.wb-main {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 20px 24px 24px;
		min-height: 0;
		min-width: 0;
		overflow-y: auto;
		container-type: inline-size;
		container-name: workbench-main;
	}
</style>
