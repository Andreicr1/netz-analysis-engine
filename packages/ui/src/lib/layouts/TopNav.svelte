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
		{#if navGroups}
			<ul role="list">
				{#each navGroups as group, gi (group.label)}
					{#if gi > 0}
						<li class="netz-topnav__drawer-divider" role="separator"></li>
					{/if}
					<li class="netz-topnav__drawer-group-label">{group.label}</li>
					{#each items.filter((item) => group.items.includes(item.href)) as item (item.href)}
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
				{/each}
			</ul>
		{:else}
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
		{/if}
	</div>
{/if}

<style>
	.netz-topnav {
		display: flex;
		align-items: center;
		height: 60px;
		padding: 0 24px;
		background:
			linear-gradient(
				180deg,
				color-mix(in srgb, var(--netz-surface-highlight, #ffffff) 92%, transparent) 0%,
				var(--netz-surface-elevated, #ffffff) 100%
			);
		border-bottom: 1px solid var(--netz-border-subtle, #e5e7eb);
		flex-shrink: 0;
		gap: 8px;
		box-shadow: var(--netz-shadow-1);
		backdrop-filter: blur(16px);
	}

	.netz-topnav__brand {
		display: flex;
		align-items: center;
		flex-shrink: 0;
		margin-right: 28px;
	}

	.netz-topnav__app-name {
		font-size: 15px;
		font-weight: 650;
		color: var(--netz-text-primary, #111827);
		white-space: nowrap;
		letter-spacing: -0.02em;
	}

	.netz-topnav__items {
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

	.netz-topnav__items::-webkit-scrollbar {
		display: none;
	}

	.netz-topnav__item {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 20px 14px 18px;
		font-size: 13px;
		font-weight: 500;
		color: var(--netz-text-secondary, #6b7280);
		text-decoration: none;
		white-space: nowrap;
		letter-spacing: -0.01em;
		border-bottom: 1px solid transparent;
		transition:
			color 140ms ease,
			border-color 140ms ease;
	}

	.netz-topnav__item:hover {
		color: var(--netz-text-primary, #111827);
	}

	.netz-topnav__item--active {
		color: var(--netz-text-primary, #111827);
		border-bottom-color: var(--netz-border-accent, #3a7bd5);
		font-weight: 600;
	}

	.netz-topnav__badge {
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
		border: 1px solid var(--netz-border-subtle, #e5e7eb);
		background: var(--netz-surface-panel, #f8fafc);
		color: var(--netz-text-secondary, #6b7280);
	}

	.netz-topnav__trailing {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-left: auto;
		flex-shrink: 0;
	}

	.netz-topnav__hamburger {
		display: none;
		align-items: center;
		justify-content: center;
		width: 38px;
		height: 38px;
		border: 1px solid var(--netz-border-subtle, #e5e7eb);
		border-radius: 9999px;
		background: var(--netz-surface-raised, #ffffff);
		color: var(--netz-text-secondary, #6b7280);
		cursor: pointer;
		margin-left: auto;
		box-shadow: var(--netz-shadow-1);
	}

	.netz-topnav__hamburger:hover {
		background: var(--netz-accent-soft, #f3f4f6);
		color: var(--netz-text-primary, #111827);
	}

	.netz-topnav__overlay {
		position: fixed;
		inset: 0;
		background: var(--netz-surface-overlay, rgba(0, 0, 0, 0.4));
		z-index: 49;
		border: none;
		cursor: default;
	}

	.netz-topnav__drawer {
		position: fixed;
		top: 68px;
		left: 12px;
		right: 12px;
		background: var(--netz-surface-panel, #ffffff);
		border: 1px solid var(--netz-border-subtle, #e5e7eb);
		border-radius: 20px;
		z-index: 50;
		padding: 10px;
		box-shadow: var(--netz-shadow-floating);
	}

	.netz-topnav__drawer ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.netz-topnav__drawer-item {
		display: block;
		padding: 11px 14px;
		font-size: 13px;
		font-weight: 500;
		color: var(--netz-text-secondary, #6b7280);
		text-decoration: none;
		border-radius: 14px;
		letter-spacing: -0.01em;
	}

	.netz-topnav__drawer-item:hover {
		background: var(--netz-accent-soft, #f3f4f6);
		color: var(--netz-text-primary, #111827);
	}

	.netz-topnav__drawer-item--active {
		color: var(--netz-text-primary, #111827);
		font-weight: 600;
		background: var(--netz-surface-highlight, #ffffff);
	}

	.netz-topnav__drawer-divider {
		height: 1px;
		margin: 6px 14px;
		background: var(--netz-border-subtle, #e5e7eb);
		list-style: none;
	}

	.netz-topnav__drawer-group-label {
		padding: 8px 14px 4px;
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--netz-text-muted, #6b7280);
		list-style: none;
	}

	/* Mobile: hide items, show hamburger */
	@media (max-width: 768px) {
		.netz-topnav__items {
			display: none;
		}
		.netz-topnav__trailing {
			gap: 0.25rem;
		}
		.netz-topnav__trailing :global(button) {
			padding: 0.375rem;
		}
		.netz-topnav__hamburger {
			display: flex;
		}
	}
</style>
