<!--
  @component AppShell
  CSS Grid layout: sidebar + main content + optional context panel.
  Responsive breakpoints: >1280 full, 1024 collapsed sidebar, 768 no panel, <600 mobile stack.
-->
<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	let {
		sidebarCollapsed = false,
		panelOpen = false,
		class: className,
		sidebar,
		main,
		panel,
		children,
	}: {
		sidebarCollapsed?: boolean;
		panelOpen?: boolean;
		class?: string;
		sidebar?: Snippet;
		main?: Snippet;
		panel?: Snippet;
		children?: Snippet;
	} = $props();

	let sidebarWidth = $derived(sidebarCollapsed ? "56px" : "240px");
	let panelWidth = $derived(panelOpen ? "400px" : "0px");
</script>

<div
	class={cn("netz-app-shell", className)}
	style:--sidebar-width={sidebarWidth}
	style:--panel-width={panelWidth}
>
	{#if sidebar}
		<aside class="netz-app-shell__sidebar" class:collapsed={sidebarCollapsed}>
			{@render sidebar()}
		</aside>
	{/if}

	<main class="netz-app-shell__main">
		{#if main}
			{@render main()}
		{:else if children}
			{@render children()}
		{/if}
	</main>

	{#if panel}
		<aside
			class="netz-app-shell__panel"
			class:open={panelOpen}
		>
			{@render panel()}
		</aside>
	{/if}
</div>

<style>
	.netz-app-shell {
		display: grid;
		grid-template-columns: var(--sidebar-width) 1fr var(--panel-width);
		grid-template-rows: 1fr;
		height: 100vh;
		width: 100vw;
		overflow: hidden;
		transition: grid-template-columns 200ms ease;
	}

	.netz-app-shell__sidebar {
		grid-column: 1;
		overflow-y: auto;
		overflow-x: hidden;
		border-right: 1px solid var(--netz-border, #e5e7eb);
		background: var(--netz-surface, #ffffff);
		transition: width 200ms ease;
		width: var(--sidebar-width);
		min-width: var(--sidebar-width);
	}

	.netz-app-shell__main {
		grid-column: 2;
		overflow-y: auto;
		overflow-x: hidden;
		background: var(--netz-surface-alt, #f9fafb);
		min-width: 0;
	}

	.netz-app-shell__panel {
		grid-column: 3;
		overflow-y: auto;
		overflow-x: hidden;
		border-left: 1px solid var(--netz-border, #e5e7eb);
		background: var(--netz-surface, #ffffff);
		width: var(--panel-width);
		transition: width 200ms ease;
	}

	.netz-app-shell__panel:not(.open) {
		width: 0;
		min-width: 0;
		border-left: none;
	}

	/* >= 1280px: full layout — default styles above */

	/* 1024px–1279px: sidebar collapsed to icons */
	@media (max-width: 1279px) {
		.netz-app-shell {
			grid-template-columns: 56px 1fr var(--panel-width);
		}
		.netz-app-shell__sidebar {
			width: 56px;
			min-width: 56px;
		}
	}

	/* 768px–1023px: no side panel */
	@media (max-width: 1023px) {
		.netz-app-shell {
			grid-template-columns: 56px 1fr;
		}
		.netz-app-shell__panel {
			position: fixed;
			top: 0;
			right: 0;
			bottom: 0;
			width: 400px;
			z-index: 40;
			box-shadow: -4px 0 24px rgba(0, 0, 0, 0.12);
			transform: translateX(100%);
			transition: transform 200ms ease;
		}
		.netz-app-shell__panel.open {
			transform: translateX(0);
		}
	}

	/* < 600px: mobile stack */
	@media (max-width: 599px) {
		.netz-app-shell {
			grid-template-columns: 1fr;
		}
		.netz-app-shell__sidebar {
			position: fixed;
			top: 0;
			left: 0;
			bottom: 0;
			width: 240px;
			z-index: 50;
			transform: translateX(-100%);
			transition: transform 200ms ease;
			box-shadow: 4px 0 24px rgba(0, 0, 0, 0.12);
		}
		.netz-app-shell__sidebar:not(.collapsed) {
			transform: translateX(0);
		}
		.netz-app-shell__panel {
			width: 100%;
		}
	}
</style>
