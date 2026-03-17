<!--
  @component TopNav
  Horizontal navigation bar — global sections (Dashboard, Risk, Analytics, etc).
  Always visible, full-width. Text items (no icons). Active = border-bottom.
  Mobile: hamburger → overlay drawer.
-->
<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { NavItem } from "../utils/types.js";
	import type { Snippet } from "svelte";

	let {
		items = [],
		appName = "Netz",
		activeHref = "",
		class: className,
		logo,
		trailing,
	}: {
		items?: NavItem[];
		appName?: string;
		activeHref?: string;
		class?: string;
		logo?: Snippet;
		trailing?: Snippet;
	} = $props();

	let mobileOpen = $state(false);

	function isActive(href: string): boolean {
		return activeHref === href || activeHref.startsWith(href + "/");
	}
</script>

<nav
	class={cn("netz-topnav", className)}
	aria-label="Global navigation"
>
	<!-- Logo + App Name -->
	<div class="netz-topnav__brand">
		{#if logo}
			{@render logo()}
		{:else}
			<span class="netz-topnav__app-name">{appName}</span>
		{/if}
	</div>

	<!-- Desktop Nav Items -->
	<ul class="netz-topnav__items" role="list">
		{#each items as item (item.href)}
			<li>
				<a
					href={item.href}
					class={cn("netz-topnav__item", isActive(item.href) && "netz-topnav__item--active")}
					aria-current={isActive(item.href) ? "page" : undefined}
				>
					{item.label}
					{#if item.badge != null}
						<span class="netz-topnav__badge">{item.badge}</span>
					{/if}
				</a>
			</li>
		{/each}
	</ul>

	<!-- Trailing slot (regime badge, org dropdown, etc) -->
	{#if trailing}
		<div class="netz-topnav__trailing">
			{@render trailing()}
		</div>
	{/if}

	<!-- Mobile hamburger -->
	<button
		class="netz-topnav__hamburger"
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
	<button class="netz-topnav__overlay" onclick={() => mobileOpen = false} aria-label="Close menu" tabindex="-1"></button>
	<div class="netz-topnav__drawer" role="dialog" aria-modal="true">
		<ul role="list">
			{#each items as item (item.href)}
				<li>
					<a
						href={item.href}
						class={cn("netz-topnav__drawer-item", isActive(item.href) && "netz-topnav__drawer-item--active")}
						onclick={() => mobileOpen = false}
					>
						{item.label}
					</a>
				</li>
			{/each}
		</ul>
	</div>
{/if}

<style>
	.netz-topnav {
		display: flex;
		align-items: center;
		height: 52px;
		padding: 0 20px;
		background: var(--netz-surface, #ffffff);
		border-bottom: 1px solid var(--netz-border, #e5e7eb);
		flex-shrink: 0;
		gap: 4px;
	}

	.netz-topnav__brand {
		display: flex;
		align-items: center;
		flex-shrink: 0;
		margin-right: 24px;
	}

	.netz-topnav__app-name {
		font-size: 15px;
		font-weight: 700;
		color: var(--netz-text-primary, #111827);
		white-space: nowrap;
		letter-spacing: -0.01em;
	}

	.netz-topnav__items {
		display: flex;
		align-items: center;
		gap: 0;
		list-style: none;
		margin: 0;
		padding: 0;
		flex: 1;
		overflow-x: auto;
		scrollbar-width: none;
	}

	.netz-topnav__items::-webkit-scrollbar {
		display: none;
	}

	.netz-topnav__item {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 14px 14px;
		font-size: 13px;
		font-weight: 500;
		color: var(--netz-text-secondary, #6b7280);
		text-decoration: none;
		white-space: nowrap;
		border-bottom: 2px solid transparent;
		transition: color 120ms ease, border-color 120ms ease;
	}

	.netz-topnav__item:hover {
		color: var(--netz-text-primary, #111827);
	}

	.netz-topnav__item--active {
		color: var(--netz-brand-primary, #2563eb);
		border-bottom-color: var(--netz-brand-primary, #2563eb);
		font-weight: 600;
	}

	.netz-topnav__badge {
		font-size: 10px;
		font-weight: 600;
		padding: 1px 5px;
		border-radius: 9999px;
		background: var(--netz-brand-primary, #2563eb);
		color: #ffffff;
	}

	.netz-topnav__trailing {
		display: flex;
		align-items: center;
		gap: 12px;
		margin-left: auto;
		flex-shrink: 0;
	}

	.netz-topnav__hamburger {
		display: none;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		border: none;
		border-radius: 6px;
		background: transparent;
		color: var(--netz-text-secondary, #6b7280);
		cursor: pointer;
		margin-left: auto;
	}

	.netz-topnav__hamburger:hover {
		background: var(--netz-surface-alt, #f3f4f6);
		color: var(--netz-text-primary, #111827);
	}

	.netz-topnav__overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.4);
		z-index: 49;
		border: none;
		cursor: default;
	}

	.netz-topnav__drawer {
		position: fixed;
		top: 52px;
		left: 0;
		right: 0;
		background: var(--netz-surface, #ffffff);
		border-bottom: 1px solid var(--netz-border, #e5e7eb);
		z-index: 50;
		padding: 8px;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
	}

	.netz-topnav__drawer ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.netz-topnav__drawer-item {
		display: block;
		padding: 10px 16px;
		font-size: 14px;
		font-weight: 500;
		color: var(--netz-text-secondary, #6b7280);
		text-decoration: none;
		border-radius: 6px;
	}

	.netz-topnav__drawer-item:hover {
		background: var(--netz-surface-alt, #f3f4f6);
		color: var(--netz-text-primary, #111827);
	}

	.netz-topnav__drawer-item--active {
		color: var(--netz-brand-primary, #2563eb);
		font-weight: 600;
		background: color-mix(in srgb, var(--netz-brand-primary, #2563eb) 8%, transparent);
	}

	/* Mobile: hide items, show hamburger */
	@media (max-width: 768px) {
		.netz-topnav__items {
			display: none;
		}
		.netz-topnav__trailing {
			display: none;
		}
		.netz-topnav__hamburger {
			display: flex;
		}
	}
</style>
