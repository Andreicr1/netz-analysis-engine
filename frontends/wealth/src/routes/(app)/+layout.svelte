<!--
  App layout — Workstation OS: fixed Sidebar + AppShell grid.
  Dark surface sidebar (netz-surface-alt) with section headers.
  Risk store initialized once, shared across all (app) routes via context.
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { setContext, getContext, onMount, type Snippet } from "svelte";
	import { AppShell, Sidebar, ThemeToggle } from "@netz/ui";
	import type { NavItem } from "@netz/ui/utils";
	import { createRiskStore, type RiskStore } from "$lib/stores/risk-store.svelte";
	import { formatLastUpdated } from "$lib/stores/stale";
	import { formatDateTime } from "@netz/ui";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { children }: { children: Snippet } = $props();

	// ── Sidebar state ──
	let sidebarCollapsed = $state(false);

	// ── Risk store (SSE-primary, poll-fallback) ──
	const riskStore = createRiskStore({
		profileIds: ["conservative", "moderate", "growth"],
		getToken,
		pollingFallbackMs: 30_000,
	});

	setContext<RiskStore>("netz:riskStore", riskStore);

	onMount(() => {
		riskStore.start();
		return () => riskStore.destroy();
	});

	// Derived banner state
	const quality = $derived(riskStore.connectionQuality);
	const bannerVisible = $derived(quality === "degraded" || quality === "offline");
	const lastComputedLabel = $derived(
		riskStore.computedAt ? formatDateTime(riskStore.computedAt) : formatLastUpdated(null)
	);

	// ── Navigation taxonomy ──
	const navItems: NavItem[] = [
		// SECTION 1: DISCOVERY & SCREENING
		{ label: "Screener", href: "/screener", icon: "🔍" },
		{ label: "Manager Screener", href: "/manager-screener", icon: "🏢" },
		{ label: "DD Reports", href: "/dd-reports", icon: "📋" },

		// SECTION 2: INVESTMENT ENGINE
		{ label: "Universe", href: "/universe", icon: "🌐" },
		{ label: "Model Portfolios", href: "/model-portfolios", icon: "📐" },
		{ label: "Portfolios", href: "/portfolios", icon: "💼" },

		// SECTION 3: RISK & INTELLIGENCE
		{ label: "Risk", href: "/risk", icon: "⚡" },
		{ label: "Analytics", href: "/analytics", icon: "📊" },
		{ label: "Exposure", href: "/exposure", icon: "🗺️" },
		{ label: "Macro", href: "/macro", icon: "🏛️" },

		// SECTION 4: CONTENT & DATA
		{ label: "Documents", href: "/documents", icon: "📄" },
		{ label: "Content", href: "/content", icon: "📰" },
	];
</script>

<AppShell sidebarCollapsed={sidebarCollapsed}>
	{#snippet sidebar()}
		<div class="netz-workstation-sidebar">
			{#if !sidebarCollapsed}
				<div class="netz-ws-header">
					<span class="netz-ws-logo">W</span>
					<span class="netz-ws-title">Wealth OS</span>
				</div>
			{:else}
				<div class="netz-ws-header netz-ws-header--collapsed">
					<span class="netz-ws-logo">W</span>
				</div>
			{/if}

			{#if !sidebarCollapsed}
				<div class="netz-ws-section-label">Discovery & Screening</div>
			{/if}
			<nav class="netz-ws-nav" aria-label="Discovery & Screening">
				{#each navItems.slice(0, 3) as item (item.href)}
					<a
						href={item.href}
						class="netz-ws-nav-item"
						class:active={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/")}
						title={sidebarCollapsed ? item.label : undefined}
						aria-current={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/") ? "page" : undefined}
					>
						<span class="netz-ws-nav-icon">{item.icon}</span>
						{#if !sidebarCollapsed}
							<span class="netz-ws-nav-label">{item.label}</span>
						{/if}
					</a>
				{/each}
			</nav>

			{#if !sidebarCollapsed}
				<div class="netz-ws-section-label">Investment Engine</div>
			{:else}
				<div class="netz-ws-divider"></div>
			{/if}
			<nav class="netz-ws-nav" aria-label="Investment Engine">
				{#each navItems.slice(3, 6) as item (item.href)}
					<a
						href={item.href}
						class="netz-ws-nav-item"
						class:active={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/")}
						title={sidebarCollapsed ? item.label : undefined}
						aria-current={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/") ? "page" : undefined}
					>
						<span class="netz-ws-nav-icon">{item.icon}</span>
						{#if !sidebarCollapsed}
							<span class="netz-ws-nav-label">{item.label}</span>
						{/if}
					</a>
				{/each}
			</nav>

			{#if !sidebarCollapsed}
				<div class="netz-ws-section-label">Risk & Intelligence</div>
			{:else}
				<div class="netz-ws-divider"></div>
			{/if}
			<nav class="netz-ws-nav" aria-label="Risk & Intelligence">
				{#each navItems.slice(6, 10) as item (item.href)}
					<a
						href={item.href}
						class="netz-ws-nav-item"
						class:active={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/")}
						title={sidebarCollapsed ? item.label : undefined}
						aria-current={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/") ? "page" : undefined}
					>
						<span class="netz-ws-nav-icon">{item.icon}</span>
						{#if !sidebarCollapsed}
							<span class="netz-ws-nav-label">{item.label}</span>
						{/if}
					</a>
				{/each}
			</nav>

			{#if !sidebarCollapsed}
				<div class="netz-ws-section-label">Content & Data</div>
			{:else}
				<div class="netz-ws-divider"></div>
			{/if}
			<nav class="netz-ws-nav" aria-label="Content & Data">
				{#each navItems.slice(10, 12) as item (item.href)}
					<a
						href={item.href}
						class="netz-ws-nav-item"
						class:active={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/")}
						title={sidebarCollapsed ? item.label : undefined}
						aria-current={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/") ? "page" : undefined}
					>
						<span class="netz-ws-nav-icon">{item.icon}</span>
						{#if !sidebarCollapsed}
							<span class="netz-ws-nav-label">{item.label}</span>
						{/if}
					</a>
				{/each}
			</nav>

			<!-- Bottom controls -->
			<div class="netz-ws-footer">
				{#if !sidebarCollapsed}
					<ThemeToggle />
				{/if}
				<button
					class="netz-ws-toggle"
					onclick={() => sidebarCollapsed = !sidebarCollapsed}
					aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
					type="button"
				>
					<svg
						class="netz-ws-toggle-icon"
						class:rotated={!sidebarCollapsed}
						width="16"
						height="16"
						viewBox="0 0 16 16"
						fill="none"
					>
						<path
							d="M6 3L11 8L6 13"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							stroke-linejoin="round"
						/>
					</svg>
				</button>
			</div>
		</div>
	{/snippet}

	{#snippet main()}
		{#if bannerVisible}
			<div
				class="flex items-center gap-2 px-4 py-2 text-sm font-medium"
				class:bg-(--netz-warning-surface)={quality === "degraded"}
				class:text-(--netz-warning-on-surface)={quality === "degraded"}
				class:bg-(--netz-error-surface)={quality === "offline"}
				class:text-(--netz-error-on-surface)={quality === "offline"}
				role="status"
				aria-live="polite"
			>
				{#if quality === "degraded"}
					<span>Live connection interrupted. Showing data from {lastComputedLabel}. Reconnecting...</span>
				{:else}
					<span>Unable to reach server. Last update: {lastComputedLabel}.</span>
					<button
						class="underline hover:no-underline"
						onclick={() => riskStore.refresh()}
					>
						Retry
					</button>
				{/if}
			</div>
		{/if}

		{@render children()}
	{/snippet}
</AppShell>

<style>
	/* ── Workstation OS Sidebar ── */
	.netz-workstation-sidebar {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--netz-surface-alt);
		border-right: 1px solid var(--netz-border-subtle);
		overflow: hidden;
	}

	/* Header */
	.netz-ws-header {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 16px 14px;
		border-bottom: 1px solid var(--netz-border-subtle);
		flex-shrink: 0;
	}

	.netz-ws-header--collapsed {
		justify-content: center;
		padding: 16px 0;
	}

	.netz-ws-logo {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border-radius: 8px;
		background: var(--netz-brand-primary);
		color: #fff;
		font-size: 14px;
		font-weight: 700;
		flex-shrink: 0;
	}

	.netz-ws-title {
		font-size: 15px;
		font-weight: 600;
		color: var(--netz-text-primary);
		white-space: nowrap;
	}

	/* Section labels */
	.netz-ws-section-label {
		padding: 16px 14px 4px;
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--netz-text-muted);
		white-space: nowrap;
	}

	.netz-ws-divider {
		margin: 8px 12px;
		border-top: 1px solid var(--netz-border-subtle);
	}

	/* Nav items */
	.netz-ws-nav {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: 4px 8px;
	}

	.netz-ws-nav-item {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 7px 10px;
		border-radius: var(--netz-radius-sm, 8px);
		color: var(--netz-text-secondary);
		text-decoration: none;
		font-size: 13px;
		font-weight: 500;
		line-height: 1.4;
		white-space: nowrap;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.netz-ws-nav-item:hover {
		background: color-mix(in srgb, var(--netz-brand-primary) 6%, transparent);
		color: var(--netz-text-primary);
	}

	.netz-ws-nav-item.active {
		background: color-mix(in srgb, var(--netz-brand-primary) 12%, transparent);
		color: var(--netz-brand-primary);
		font-weight: 600;
	}

	.netz-ws-nav-icon {
		flex-shrink: 0;
		width: 20px;
		height: 20px;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 15px;
	}

	.netz-ws-nav-label {
		overflow: hidden;
		text-overflow: ellipsis;
		flex: 1;
	}

	/* Footer */
	.netz-ws-footer {
		margin-top: auto;
		padding: 8px;
		border-top: 1px solid var(--netz-border-subtle);
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
	}

	.netz-ws-toggle {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border: none;
		border-radius: var(--netz-radius-sm, 6px);
		background: transparent;
		color: var(--netz-text-muted);
		cursor: pointer;
		transition: color 120ms ease, background-color 120ms ease;
		margin-left: auto;
	}

	.netz-ws-toggle:hover {
		color: var(--netz-text-primary);
		background: color-mix(in srgb, var(--netz-brand-primary) 8%, transparent);
	}

	.netz-ws-toggle-icon {
		transition: transform 200ms ease;
	}

	.netz-ws-toggle-icon.rotated {
		transform: rotate(180deg);
	}
</style>
