<!--
  App layout — Workstation OS: fixed Sidebar + AppShell grid.
  Dark surface sidebar (netz-surface-alt) with section headers.
  Risk store initialized once, shared across all (app) routes via context.
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { setContext, getContext, onMount, type Snippet } from "svelte";
	import { ThemeToggle } from "@netz/ui";
	import { createRiskStore, type RiskStore } from "$lib/stores/risk-store.svelte";
	import {
		Search, Building2, ClipboardList, Globe,
		Briefcase, Zap, BarChart2, Map,
		Landmark, FileText, Newspaper, Folders,
		Search as SearchIcon, Bot
	} from "lucide-svelte";
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	interface SidebarNavItem {
		label: string;
		href: string;
		icon: any;
	}

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

	// ── Navigation taxonomy ──
	const navItems: SidebarNavItem[] = [
		// SECTION 1: DISCOVERY & SCREENING
		{ label: "Screener", href: "/screener", icon: Search },
		{ label: "Manager Screener", href: "/manager-screener", icon: Building2 },
		{ label: "DD Reports", href: "/dd-reports", icon: ClipboardList },

		// SECTION 2: INVESTMENT ENGINE
		{ label: "Universe", href: "/universe", icon: Globe },
		{ label: "Model Portfolios", href: "/model-portfolios", icon: Folders },
		{ label: "Portfolios", href: "/portfolios", icon: Briefcase },

		// SECTION 3: RISK & INTELLIGENCE
		{ label: "Risk", href: "/risk", icon: Zap },
		{ label: "Analytics", href: "/analytics", icon: BarChart2 },
		{ label: "Exposure", href: "/exposure", icon: Map },
		{ label: "Macro", href: "/macro", icon: Landmark },

		// SECTION 4: CONTENT & DATA
		{ label: "Documents", href: "/documents", icon: FileText },
		{ label: "Content", href: "/content", icon: Newspaper },
	];
</script>

<div class="netz-shell" style:--sidebar-w={sidebarCollapsed ? "56px" : "240px"}>
	<aside class="netz-shell-sidebar">
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
					{@const Icon = item.icon}
					<a
						href={item.href}
						class="netz-ws-nav-item"
						class:active={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/")}
						title={sidebarCollapsed ? item.label : undefined}
						aria-current={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/") ? "page" : undefined}
					>
						<span class="netz-ws-nav-icon"><Icon size={18} strokeWidth={1.5} /></span>
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
					{@const Icon = item.icon}
					<a
						href={item.href}
						class="netz-ws-nav-item"
						class:active={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/")}
						title={sidebarCollapsed ? item.label : undefined}
						aria-current={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/") ? "page" : undefined}
					>
						<span class="netz-ws-nav-icon"><Icon size={18} strokeWidth={1.5} /></span>
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
					{@const Icon = item.icon}
					<a
						href={item.href}
						class="netz-ws-nav-item"
						class:active={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/")}
						title={sidebarCollapsed ? item.label : undefined}
						aria-current={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/") ? "page" : undefined}
					>
						<span class="netz-ws-nav-icon"><Icon size={18} strokeWidth={1.5} /></span>
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
					{@const Icon = item.icon}
					<a
						href={item.href}
						class="netz-ws-nav-item"
						class:active={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/")}
						title={sidebarCollapsed ? item.label : undefined}
						aria-current={$page.url.pathname === item.href || $page.url.pathname.startsWith(item.href + "/") ? "page" : undefined}
					>
						<span class="netz-ws-nav-icon"><Icon size={18} strokeWidth={1.5} /></span>
						{#if !sidebarCollapsed}
							<span class="netz-ws-nav-label">{item.label}</span>
						{/if}
					</a>
				{/each}
			</nav>

			<!-- Bottom controls -->
			<div class="netz-ws-footer">
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
	</aside>

	<main class="netz-shell-main">
		<!-- Top Bar: Global Search + AI Agent + Theme Toggle -->
		<header class="netz-topbar">
			<div class="netz-topbar-search">
				<SearchIcon size={15} strokeWidth={1.5} class="netz-topbar-search-icon" />
				<input
					type="text"
					class="netz-topbar-search-input"
					placeholder="Search…"
					readonly
				/>
				<kbd class="netz-topbar-kbd">/</kbd>
			</div>

			<div class="netz-topbar-actions">
				<button class="netz-topbar-btn netz-topbar-btn--ai" type="button" title="AI Assistant">
					<Bot size={18} strokeWidth={1.5} />
				</button>
				<ThemeToggle />
			</div>
		</header>

		<div class="netz-shell-content">
			{@render children()}
		</div>
	</main>
</div>

<style>
	/* ── Shell grid (replaces AppShell for direct $state reactivity) ── */
	.netz-shell {
		display: grid;
		grid-template-columns: var(--sidebar-w) 1fr;
		height: 100vh;
		width: 100vw;
		overflow: hidden;
		transition: grid-template-columns 200ms ease;
	}

	.netz-shell-sidebar {
		overflow-y: auto;
		overflow-x: hidden;
		border-right: 1px solid var(--netz-border-subtle);
		transition: width 200ms ease;
	}

	.netz-shell-main {
		overflow: hidden;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}

	/* ── Top Bar ── */
	.netz-topbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 var(--netz-space-inline-lg, 20px);
		height: 48px;
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-elevated);
		flex-shrink: 0;
	}

	.netz-topbar-search {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
		height: 32px;
		padding: 0 var(--netz-space-inline-sm, 10px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 8px);
		background: var(--netz-surface);
		cursor: pointer;
		transition: border-color 120ms ease;
		min-width: 200px;
		max-width: 320px;
	}

	.netz-topbar-search:hover {
		border-color: var(--netz-border-focus);
	}

	.netz-topbar-search :global(.netz-topbar-search-icon) {
		color: var(--netz-text-muted);
		flex-shrink: 0;
	}

	.netz-topbar-search-input {
		flex: 1;
		border: none;
		background: transparent;
		color: var(--netz-text-muted);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
		cursor: pointer;
		outline: none;
	}

	.netz-topbar-kbd {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 20px;
		height: 20px;
		padding: 0 5px;
		border: 1px solid var(--netz-border);
		border-radius: 4px;
		background: var(--netz-surface-alt);
		color: var(--netz-text-muted);
		font-size: 11px;
		font-family: var(--netz-font-mono);
		font-weight: 500;
		line-height: 1;
	}

	.netz-topbar-actions {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
	}

	.netz-topbar-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 8px);
		background: transparent;
		color: var(--netz-text-secondary);
		cursor: pointer;
		transition: color 120ms ease, background-color 120ms ease, border-color 120ms ease;
	}

	.netz-topbar-btn:hover {
		color: var(--netz-text-primary);
		background: var(--netz-surface-alt);
	}

	.netz-topbar-btn--ai {
		border-color: var(--netz-brand-highlight);
		color: var(--netz-brand-highlight);
	}

	.netz-topbar-btn--ai:hover {
		background: color-mix(in srgb, var(--netz-brand-highlight) 10%, transparent);
		color: var(--netz-brand-highlight);
	}

	/* ── Scrollable content area ── */
	.netz-shell-content {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
	}

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
