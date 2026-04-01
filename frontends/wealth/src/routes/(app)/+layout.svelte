<!--
  App layout — InvestIntell Workstation: fixed Sidebar + AppShell grid.
  Thunder Client–style sidebar with collapsible two-level sections.
  Risk store initialized once, shared across all (app) routes via context.
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { setContext, getContext, type Snippet } from "svelte";
	import { ThemeToggle } from "@investintell/ui";
	import { createRiskStore, type RiskStore } from "$lib/stores/risk-store.svelte";
	import ConnectionStatus from "$lib/components/ConnectionStatus.svelte";
	import {
		ShieldCheck, Stack, Database, Briefcase, MagnifyingGlass,
		ClipboardText, ChartBar, Globe, Lightning, Newspaper,
		FileText, GearSix, Robot, CaretDown,
	} from "phosphor-svelte";
	import AiAgentDrawer from "$lib/components/AiAgentDrawer.svelte";
	import GlobalSearch from "$lib/components/GlobalSearch.svelte";

	interface SidebarItem {
		label: string;
		href: string;
		icon: any; // eslint-disable-line @typescript-eslint/no-explicit-any
	}

	interface SidebarSection {
		id: string;
		label: string;
		defaultOpen: boolean;
		items: SidebarItem[];
	}

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { children }: { children: Snippet } = $props();

	// ── Sidebar state ──
	let sidebarCollapsed = $state(false);

	// ── AI Agent drawer state ──
	let agentOpen = $state(false);

	// ── Global search state ──
	let searchOpen = $state(false);

	// ── Risk store (SSE-primary, poll-fallback) ──
	const riskStore = createRiskStore({
		profileIds: ["conservative", "moderate", "growth"],
		getToken,
		pollingFallbackMs: 30_000,
	});

	setContext<RiskStore>("netz:riskStore", riskStore);
	// riskStore.start() is NOT called here — Dashboard and Risk pages own their lifecycle.

	// ── Navigation taxonomy — institutional process flow ──
	const sections: SidebarSection[] = [
		{
			id: "overview", label: "Overview", defaultOpen: true,
			items: [
				{ label: "Dashboard", href: "/dashboard", icon: ChartBar },
			],
		},
		{
			id: "research", label: "Research", defaultOpen: true,
			items: [
				{ label: "Screener",        href: "/screener",   icon: MagnifyingGlass },
				{ label: "DD Reports",      href: "/dd-reports", icon: ClipboardText },
				{ label: "Assets Universe", href: "/universe",   icon: Database },
			],
		},
		{
			id: "portfolio", label: "Portfolio", defaultOpen: true,
			items: [
				{ label: "Investment Policy", href: "/investment-policy", icon: ShieldCheck },
				{ label: "Macro",             href: "/macro",             icon: Globe },
				{ label: "Portfolio Builder", href: "/model-portfolios",  icon: Stack },
				{ label: "Portfolios",        href: "/portfolios",        icon: Briefcase },
			],
		},
		{
			id: "intelligence", label: "Intelligence", defaultOpen: true,
			items: [
				{ label: "Analytics", href: "/analytics", icon: ChartBar },
				{ label: "Risk",      href: "/risk",      icon: Lightning },
			],
		},
		{
			id: "content", label: "Content", defaultOpen: true,
			items: [
				{ label: "Content",   href: "/content",   icon: Newspaper },
				{ label: "Documents", href: "/documents", icon: FileText },
			],
		},
		{
			id: "system", label: "System", defaultOpen: false,
			items: [
				{ label: "System", href: "/settings/system", icon: GearSix },
			],
		},
	];

	// ── Collapsible section state ──
	let openSections = $state<Set<string>>(
		new Set(sections.filter(s => s.defaultOpen).map(s => s.id))
	);

	function toggleSection(id: string) {
		const next = new Set(openSections);
		next.has(id) ? next.delete(id) : next.add(id);
		openSections = next;
	}

	function isActive(href: string): boolean {
		return $page.url.pathname === href || $page.url.pathname.startsWith(href + "/");
	}
</script>

<div class="ii-shell" style:--sidebar-w={sidebarCollapsed ? "56px" : "256px"}>
	<aside class="ii-sidebar-wrapper">
		<div class="ii-sidebar">
			<!-- Scrollable nav area — no header, logo lives in topbar -->
			<div class="sidebar-nav">
				{#each sections as section (section.id)}
					{#if !sidebarCollapsed}
						<!-- Section header — clickable accordion toggle -->
						<button
							class="section-header"
							onclick={() => toggleSection(section.id)}
							aria-expanded={openSections.has(section.id)}
							type="button"
						>
							<span class="section-label">{section.label}</span>
							<CaretDown
								size={12}
								weight="light"
								class="section-chevron {openSections.has(section.id) ? 'open' : ''}"
							/>
						</button>

						<!-- Accordion body -->
						<div class="section-items" class:open={openSections.has(section.id)}>
							<nav class="section-items-inner" aria-label={section.label}>
								{#each section.items as item (item.href)}
									{@const Icon = item.icon}
									<a
										href={item.href}
										class="nav-item"
										class:active={isActive(item.href)}
										aria-current={isActive(item.href) ? "page" : undefined}
									>
										<span class="nav-icon"><Icon size={18} weight="light" /></span>
										<span class="nav-label">{item.label}</span>
									</a>
								{/each}
							</nav>
						</div>
					{:else}
						<!-- Collapsed: divider between sections, icon-only items -->
						{#if section.id !== "overview"}
							<div class="sidebar-divider"></div>
						{/if}
						<nav class="section-items-collapsed" aria-label={section.label}>
							{#each section.items as item (item.href)}
								{@const Icon = item.icon}
								<a
									href={item.href}
									class="nav-item nav-item--icon-only"
									class:active={isActive(item.href)}
									title={item.label}
									aria-current={isActive(item.href) ? "page" : undefined}
								>
									<span class="nav-icon"><Icon size={18} weight="light" /></span>
								</a>
							{/each}
						</nav>
					{/if}
				{/each}
			</div>

			<!-- Bottom controls -->
			<div class="sidebar-footer">
				<button
					class="sidebar-toggle"
					onclick={() => sidebarCollapsed = !sidebarCollapsed}
					aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
					type="button"
				>
					<svg
						class="sidebar-toggle-icon"
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

	<!-- Top Bar — direct child of grid, spans BOTH columns -->
	<header class="ii-topbar">
		<div class="ii-topbar-brand">
			<!-- Hourglass SVG mark (inline) -->
			<svg width="20" height="24" viewBox="0 0 20 24" fill="none" xmlns="http://www.w3.org/2000/svg">
				<style>
					.logo-top    { fill: var(--ii-brand-primary); }
					.logo-bottom { fill: var(--ii-text-tertiary); }
					.logo-line-top    { stroke: var(--ii-brand-primary); }
					.logo-line-bottom { stroke: var(--ii-text-tertiary); }
				</style>
				<circle class="logo-top" cx="4"  cy="4"  r="1.5"/>
				<circle class="logo-top" cx="10" cy="4"  r="1.5"/>
				<circle class="logo-top" cx="16" cy="4"  r="1.5"/>
				<circle class="logo-top" cx="10" cy="12" r="2"/>
				<circle class="logo-bottom" cx="4"  cy="20" r="1.5"/>
				<circle class="logo-bottom" cx="10" cy="20" r="1.5"/>
				<circle class="logo-bottom" cx="16" cy="20" r="1.5"/>
				<line class="logo-line-top"    x1="4"  y1="4"  x2="10" y2="12" stroke-width="1" stroke-linecap="round"/>
				<line class="logo-line-top"    x1="16" y1="4"  x2="10" y2="12" stroke-width="1" stroke-linecap="round"/>
				<line class="logo-line-bottom" x1="4"  y1="20" x2="10" y2="12" stroke-width="1" stroke-linecap="round"/>
				<line class="logo-line-bottom" x1="16" y1="20" x2="10" y2="12" stroke-width="1" stroke-linecap="round"/>
			</svg>
			{#if !sidebarCollapsed}
				<span class="ii-topbar-wordmark">
					<span class="ii-topbar-invest">invest</span><span class="ii-topbar-intell">intell</span>
				</span>
			{/if}
		</div>
		<div class="ii-topbar-divider"></div>

			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div class="ii-topbar-search" onclick={() => searchOpen = true}>
				<MagnifyingGlass size={15} weight="light" class="ii-topbar-search-icon" />
				<span class="ii-topbar-search-input">Search…</span>
				<kbd class="ii-topbar-kbd">{typeof navigator !== "undefined" && navigator?.platform?.includes("Mac") ? "⌘K" : "Ctrl+K"}</kbd>
			</div>

			<div class="ii-topbar-actions">
				<ConnectionStatus quality={riskStore.connectionQuality} />
				<button class="ii-topbar-btn ii-topbar-btn--ai" type="button" title="AI Assistant" onclick={() => agentOpen = !agentOpen}>
					<Robot size={18} weight="light" />
				</button>
				<ThemeToggle />
			</div>
		</header>

	<main class="ii-main">
		<div class="ii-content">
			{@render children()}
		</div>
	</main>
</div>

<AiAgentDrawer open={agentOpen} onclose={() => agentOpen = false} />
<GlobalSearch bind:open={searchOpen} />

<style>
	/* ── Shell grid — topbar spans full width, sidebar+content below ── */
	.ii-shell {
		display: grid;
		grid-template-columns: var(--sidebar-w) 1fr;
		grid-template-rows: 58px 1fr;
		height: 100vh;
		width: 100vw;
		overflow: hidden;
		transition: grid-template-columns 200ms var(--ii-ease-out, cubic-bezier(0,0,.2,1));
	}

	.ii-sidebar-wrapper {
		grid-column: 1;
		grid-row: 2;
		overflow-y: auto;
		overflow-x: hidden;
		border-right: 1px solid var(--ii-border-subtle);
		transition: width 200ms var(--ii-ease-out, cubic-bezier(0,0,.2,1));
	}

	.ii-main {
		grid-column: 2;
		grid-row: 2;
		overflow: hidden;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}

	/* ── Top Bar — spans BOTH columns (full width) ── */
	.ii-topbar {
		grid-column: 1 / -1;
		grid-row: 1;
		display: flex;
		align-items: center;
		gap: 0;
		height: 58px;
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface);
		flex-shrink: 0;
		overflow: hidden;
	}

	/* ── Topbar brand section — aligns with sidebar width ── */
	.ii-topbar-brand {
		display: flex;
		align-items: center;
		gap: 9px;
		width: var(--sidebar-w);
		min-width: var(--sidebar-w);
		max-width: var(--sidebar-w);
		padding: 0 14px;
		flex-shrink: 0;
		overflow: hidden;
		transition: width 200ms var(--ii-ease-out, cubic-bezier(0,0,.2,1)),
		            min-width 200ms var(--ii-ease-out, cubic-bezier(0,0,.2,1));
	}

	.ii-topbar-wordmark {
		font-family: var(--ii-font-sans);
		font-size: 16px;
		font-weight: 400;
		letter-spacing: -0.4px;
		white-space: nowrap;
		overflow: hidden;
	}

	.ii-topbar-invest {
		color: var(--ii-text-primary);
	}

	.ii-topbar-intell {
		color: var(--ii-brand-primary);
		font-weight: 600;
	}

	/* Vertical divider between brand and search */
	.ii-topbar-divider {
		width: 1px;
		height: 20px;
		background: var(--ii-border-subtle);
		flex-shrink: 0;
		margin: 0 16px 0 0;
	}

	.ii-topbar-search {
		display: flex;
		align-items: center;
		gap: 6px;
		height: 32px;
		padding: 0 10px;
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-md, 6px);
		background: var(--ii-bg, var(--ii-surface));
		cursor: pointer;
		transition: border-color 120ms ease;
		min-width: 200px;
		max-width: 320px;
	}

	.ii-topbar-search:hover { border-color: var(--ii-border-focus); }

	.ii-topbar-search :global(.ii-topbar-search-icon) {
		color: var(--ii-text-muted); flex-shrink: 0;
	}

	.ii-topbar-search-input {
		flex: 1; border: none; background: transparent;
		color: var(--ii-text-muted); font-size: 0.8125rem;
		font-family: var(--ii-font-sans); cursor: pointer; outline: none;
	}

	.ii-topbar-kbd {
		display: inline-flex; align-items: center; justify-content: center;
		min-width: 20px; height: 20px; padding: 0 5px;
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-xs, 4px);
		background: var(--ii-surface-alt);
		color: var(--ii-text-muted); font-size: 11px;
		font-family: var(--ii-font-mono); font-weight: 500; line-height: 1;
	}

	.ii-topbar-actions {
		display: flex; align-items: center; gap: 6px;
		margin-left: auto;
		padding-right: 16px;
	}

	.ii-topbar-btn {
		display: flex; align-items: center; justify-content: center;
		width: 32px; height: 32px;
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-md, 6px);
		background: transparent; color: var(--ii-text-secondary);
		cursor: pointer;
		transition: color 120ms ease, background-color 120ms ease, border-color 120ms ease;
	}

	.ii-topbar-btn:hover { color: var(--ii-text-primary); background: var(--ii-surface-alt); }

	.ii-topbar-btn--ai { border-color: var(--ii-brand-secondary); color: var(--ii-brand-secondary); }
	.ii-topbar-btn--ai:hover {
		background: color-mix(in srgb, var(--ii-brand-secondary) 10%, transparent);
		color: var(--ii-brand-secondary);
	}

	/* ── Scrollable content area ── */
	.ii-content {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		padding: 0 48px;
		background: var(--ii-bg, #f5f8fd);
	}

	@media (max-width: 767px) {
		.ii-content {
			padding: 0 16px;
		}
	}

	/* ── Sidebar container ── */
	.ii-sidebar {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--ii-surface);
		overflow: hidden;
		font-feature-settings: "rlig" 1, "calt" 1, "ss01" 1;
		-webkit-font-smoothing: antialiased;
	}

	/* ── Scrollable nav ── */
	.sidebar-nav {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		scrollbar-width: thin;
		scrollbar-color: var(--ii-border) transparent;
		padding-top: 24px;
		padding-left: 16px;
		padding-right: 16px;
	}

	/* ── Section header — clickable ── */
	.section-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: 0 16px;
		margin-top: 32px;
		margin-bottom: 12px;
		border: none;
		background: transparent;
		cursor: pointer;
		user-select: none;
	}

	.section-header:first-child {
		margin-top: 0;
	}

	.section-label {
		font-size: 10px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 2px;
		color: var(--ii-text-tertiary);
	}

	.section-header :global(.section-chevron) {
		color: var(--ii-text-tertiary);
		transition: transform 200ms var(--ii-ease-out, cubic-bezier(0,0,.2,1));
		flex-shrink: 0;
	}

	.section-header :global(.section-chevron.open) {
		transform: rotate(0deg);
	}

	.section-header :global(.section-chevron:not(.open)) {
		transform: rotate(-90deg);
	}

	/* ── Accordion — grid trick (no height hacks) ── */
	.section-items {
		display: grid;
		grid-template-rows: 0fr;
		overflow: hidden;
		transition: grid-template-rows 220ms var(--ii-ease-out, cubic-bezier(0,0,.2,1));
	}

	.section-items.open {
		grid-template-rows: 1fr;
	}

	.section-items-inner {
		min-height: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 0;
		margin-left: 0;
		position: relative;
	}

	/* ── Collapsed sections ── */
	.section-items-collapsed {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: 4px 8px;
	}

	.sidebar-divider {
		margin: 6px 12px;
		border-top: 1px solid var(--ii-border-subtle);
	}

	/* ── Nav item ── */
	.nav-item {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 10px 16px;
		border-radius: 14px;
		color: var(--ii-text-secondary);
		font-size: 13px;
		font-weight: 600;
		line-height: 1;
		transition: background 120ms ease, color 120ms ease;
		text-decoration: none;
		white-space: nowrap;
	}

	.nav-item:hover {
		background: var(--ii-bg-hover);
		color: var(--ii-text-primary);
	}

	.nav-item.active {
		background: var(--ii-accent-soft);
		color: var(--ii-brand-primary);
		font-weight: 700;
	}

	.nav-item--icon-only {
		justify-content: center;
		padding: 7px 0;
	}

	.nav-icon {
		flex-shrink: 0;
		width: 20px;
		height: 20px;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.nav-label {
		overflow: hidden;
		text-overflow: ellipsis;
		flex: 1;
	}

	/* ── Footer ── */
	.sidebar-footer {
		margin-top: auto;
		padding: 8px;
		border-top: 1px solid var(--ii-border-subtle);
		display: flex;
		align-items: center;
		justify-content: flex-end;
		flex-shrink: 0;
	}

	.sidebar-toggle {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border: none;
		border-radius: var(--ii-radius-md, 6px);
		background: transparent;
		color: var(--ii-text-muted);
		cursor: pointer;
		transition: color 120ms ease, background-color 120ms ease;
	}

	.sidebar-toggle:hover {
		color: var(--ii-text-primary);
		background: color-mix(in srgb, var(--ii-brand-primary) 8%, transparent);
	}

	.sidebar-toggle-icon {
		transition: transform 200ms var(--ii-ease-out, cubic-bezier(0,0,.2,1));
	}

	.sidebar-toggle-icon.rotated {
		transform: rotate(180deg);
	}
</style>
