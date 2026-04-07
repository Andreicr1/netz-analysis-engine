<!--
  @component TopNav
  Horizontal navigation bar — global sections (Dashboard, Risk, Analytics, etc).
  Always visible, full-width. Text items (no icons). Active = border-bottom.
  Mobile: hamburger → overlay drawer.
-->
<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { NavItem } from "../../utils/types.js";
	import type { Snippet } from "svelte";

	let {
		items = [],
		appName = "Netz",
		activeHref = "",
		class: className,
		logo,
		trailing,
		navGroups,
	}: {
		items?: NavItem[];
		appName?: string;
		activeHref?: string;
		class?: string;
		logo?: Snippet;
		trailing?: Snippet;
		navGroups?: Array<{ label: string; items: string[] }>;
	} = $props();

	let mobileOpen = $state(false);

	function isActive(href: string): boolean {
		return activeHref === href || activeHref.startsWith(href + "/");
	}
</script>

<nav
	class={cn("ii-topnav", className)}
	aria-label="Global navigation"
>
	<!-- Logo + App Name -->
	<div class="ii-topnav__brand">
		{#if logo}
			{@render logo()}
		{:else}
			<span class="ii-topnav__app-name">{appName}</span>
		{/if}
	</div>

	<!-- Desktop Nav Items -->
	<ul class="ii-topnav__items" role="list">
		{#each items as item (item.href)}
			<li>
				<a
					href={item.href}
					class={cn("ii-topnav__item", isActive(item.href) && "ii-topnav__item--active")}
					aria-current={isActive(item.href) ? "page" : undefined}
				>
					{item.label}
					{#if item.badge != null}
						<span class="ii-topnav__badge">{item.badge}</span>
					{/if}
				</a>
			</li>
		{/each}
	</ul>

	<!-- Trailing slot (regime badge, org dropdown, etc) -->
	{#if trailing}
		<div class="ii-topnav__trailing">
			{@render trailing()}
		</div>
	{/if}

	<!-- Mobile hamburger -->
	<button
		class="ii-topnav__hamburger"
		onclick={() => mobileOpen = !mobileOpen}
		aria-label={mobileOpen ? "Close menu" : "Open menu"}
		type="button"
	>
		<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
			{#if mobileOpen}
				<path d="M18 6L6 18M6 6l12 12" stroke-linecap="round" />
			{:else}
				<path d="M3 12h18M3 6h18M3 18h18" stroke-linecap="round" />
			{/if}
		</svg>
	</button>
</nav>

<!-- Mobile overlay drawer -->
{#if mobileOpen}
	<button class="ii-topnav__overlay" onclick={() => mobileOpen = false} aria-label="Close menu" tabindex="-1"></button>
	<div class="ii-topnav__drawer" role="dialog" aria-modal="true">
		{#if navGroups}
			<ul role="list">
				{#each navGroups as group, gi (group.label)}
					{#if gi > 0}
						<li class="ii-topnav__drawer-divider" role="separator"></li>
					{/if}
					<li class="ii-topnav__drawer-group-label">{group.label}</li>
					{#each items.filter((item) => group.items.includes(item.href)) as item (item.href)}
						<li>
							<a
								href={item.href}
								class={cn("ii-topnav__drawer-item", isActive(item.href) && "ii-topnav__drawer-item--active")}
								onclick={() => mobileOpen = false}
							>
								{item.label}
							</a>
						</li>
					{/each}
				{/each}
			</ul>
		{:else}
			<ul role="list">
				{#each items as item (item.href)}
					<li>
						<a
							href={item.href}
							class={cn("ii-topnav__drawer-item", isActive(item.href) && "ii-topnav__drawer-item--active")}
							onclick={() => mobileOpen = false}
						>
							{item.label}
						</a>
					</li>
				{/each}
			</ul>
		{/if}
	</div>
{/if}

<style>
	.ii-topnav {
		display: flex;
		align-items: center;
		height: 88px;
		padding: 0 32px;
		background: #000000;
		border-bottom: none;
		flex-shrink: 0;
		gap: 8px;
		color: #ffffff;
	}

	.ii-topnav__brand {
		display: flex;
		align-items: center;
		flex-shrink: 0;
		margin-right: 28px;
	}

	.ii-topnav__app-name {
		font-size: 15px;
		font-weight: 650;
		color: #ffffff;
		white-space: nowrap;
		letter-spacing: -0.02em;
	}

	.ii-topnav__items {
		display: flex;
		align-items: center;
		gap: 0;
		list-style: none;
		margin: 0;
		padding: 0;
		flex: 1;
		min-width: 0;
		overflow-x: auto;
		scrollbar-width: none;
	}

	.ii-topnav__items::-webkit-scrollbar {
		display: none;
	}

	.ii-topnav__item {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 20px 14px 18px;
		font-size: 13px;
		font-weight: 500;
		color: rgba(255, 255, 255, 0.6);
		text-decoration: none;
		white-space: nowrap;
		letter-spacing: -0.01em;
		border-bottom: 1px solid transparent;
		transition:
			color 140ms ease,
			border-color 140ms ease;
	}

	.ii-topnav__item:hover {
		color: #ffffff;
	}

	.ii-topnav__item--active {
		color: #ffffff;
		border-bottom-color: #0177fb;
		font-weight: 600;
	}

	.ii-topnav__badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 18px;
		font-size: 10px;
		font-weight: 600;
		padding: 0 6px;
		letter-spacing: 0.02em;
		border-radius: 9999px;
		border: 1px solid rgba(255, 255, 255, 0.1);
		background: rgba(255, 255, 255, 0.1);
		color: rgba(255, 255, 255, 0.7);
	}

	.ii-topnav__trailing {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-left: auto;
		flex-shrink: 0;
	}

	.ii-topnav__hamburger {
		display: none;
		align-items: center;
		justify-content: center;
		width: 38px;
		height: 38px;
		border: none;
		border-radius: 9999px;
		background: transparent;
		color: rgba(255, 255, 255, 0.6);
		cursor: pointer;
		margin-left: auto;
	}

	.ii-topnav__hamburger:hover {
		background: rgba(255, 255, 255, 0.1);
		color: #ffffff;
	}

	.ii-topnav__overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		z-index: 49;
		border: none;
		cursor: default;
	}

	.ii-topnav__drawer {
		position: fixed;
		top: 96px;
		left: 12px;
		right: 12px;
		background: #1a1b20;
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 20px;
		z-index: 50;
		padding: 10px;
	}

	.ii-topnav__drawer ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.ii-topnav__drawer-item {
		display: block;
		padding: 11px 14px;
		font-size: 13px;
		font-weight: 500;
		color: rgba(255, 255, 255, 0.6);
		text-decoration: none;
		border-radius: 14px;
		letter-spacing: -0.01em;
	}

	.ii-topnav__drawer-item:hover {
		background: rgba(255, 255, 255, 0.05);
		color: #ffffff;
	}

	.ii-topnav__drawer-item--active {
		color: #ffffff;
		font-weight: 600;
		background: rgba(255, 255, 255, 0.1);
	}

	.ii-topnav__drawer-divider {
		height: 1px;
		margin: 6px 14px;
		background: rgba(255, 255, 255, 0.1);
		list-style: none;
	}

	.ii-topnav__drawer-group-label {
		padding: 8px 14px 4px;
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: rgba(255, 255, 255, 0.4);
		list-style: none;
	}

	/* Mobile: hide items, show hamburger */
	@media (max-width: 768px) {
		.ii-topnav__items {
			display: none;
		}
		.ii-topnav__trailing {
			gap: 0.25rem;
		}
		.ii-topnav__trailing :global(button) {
			padding: 0.375rem;
		}
		.ii-topnav__hamburger {
			display: flex;
		}
	}
</style>
