<!--
  TerminalGlobalNav — ultrathin 32px global navigation bar.

  Provides routing across the three Terminal OS surfaces:
  PORTFOLIOS, SCREENER, RESEARCH. Sits at the absolute top
  of the (terminal) layout group, above all workspace content.
-->
<script lang="ts">
	import { page } from "$app/stores";

	const tabs = [
		{ label: "PORTFOLIOS", href: "/portfolio/live" },
		{ label: "SCREENER", href: "/terminal-screener" },
		{ label: "RESEARCH", href: "/research" },
	] as const;

	const currentPath = $derived($page.url.pathname);

	function isActive(href: string): boolean {
		return currentPath.startsWith(href);
	}
</script>

<nav class="tg-nav" aria-label="Terminal global navigation">
	{#each tabs as tab}
		<a
			class="tg-nav-tab"
			class:active={isActive(tab.href)}
			href={tab.href}
			data-sveltekit-preload-data="hover"
		>
			{tab.label}
		</a>
	{/each}
</nav>

<style>
	.tg-nav {
		display: flex;
		align-items: center;
		gap: 0;
		height: 32px;
		min-height: 32px;
		max-height: 32px;
		background: #05080f;
		padding: 0 16px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.04);
		flex-shrink: 0;
	}

	.tg-nav-tab {
		display: flex;
		align-items: center;
		height: 100%;
		padding: 0 14px;
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		text-decoration: none;
		color: #5a6577;
		border-bottom: 2px solid transparent;
		transition:
			color 120ms ease,
			border-color 120ms ease;
		cursor: pointer;
		user-select: none;
	}

	.tg-nav-tab:hover {
		color: #8a94a6;
	}

	.tg-nav-tab.active {
		color: #e2e8f0;
		border-bottom-color: #2d7ef7;
	}
</style>
