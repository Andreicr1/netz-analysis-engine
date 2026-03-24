<!--
  App layout — Workstation OS: fixed Sidebar + AppShell grid.
  Thunder Client–style sidebar with collapsible two-level sections.
  Risk store initialized once, shared across all (app) routes via context.
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { setContext, getContext, onMount, type Snippet } from "svelte";
	import { ThemeToggle } from "@netz/ui";
	import { createRiskStore, type RiskStore } from "$lib/stores/risk-store.svelte";
	import {
		Search, ClipboardList, Globe,
		Briefcase, Zap, BarChart2, Map,
		Landmark, FileText, Newspaper, Folders,
		Search as SearchIcon, Bot, PieChart, ChevronRight
	} from "lucide-svelte";

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

	// ── Navigation taxonomy — sectioned ──
	const sections: SidebarSection[] = [
		{
			id: "discovery", label: "Discovery & Screening", defaultOpen: true,
			items: [
				{ label: "Screener",   href: "/screener",   icon: Search },
				{ label: "DD Reports", href: "/dd-reports", icon: ClipboardList },
			],
		},
		{
			id: "investment", label: "Investment Engine", defaultOpen: true,
			items: [
				{ label: "Universe",         href: "/universe",         icon: Globe },
				{ label: "Model Portfolios", href: "/model-portfolios", icon: Folders },
				{ label: "Portfolios",       href: "/portfolios",       icon: Briefcase },
				{ label: "Allocation",       href: "/allocation",       icon: PieChart },
			],
		},
		{
			id: "risk", label: "Risk & Intelligence", defaultOpen: true,
			items: [
				{ label: "Risk",      href: "/risk",      icon: Zap },
				{ label: "Analytics", href: "/analytics", icon: BarChart2 },
				{ label: "Exposure",  href: "/exposure",  icon: Map },
				{ label: "Macro",     href: "/macro",     icon: Landmark },
			],
		},
		{
			id: "content", label: "Content & Data", defaultOpen: true,
			items: [
				{ label: "Documents", href: "/documents", icon: FileText },
				{ label: "Content",   href: "/content",   icon: Newspaper },
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

<div class="netz-shell" style:--sidebar-w={sidebarCollapsed ? "56px" : "256px"}>
	<aside class="netz-shell-sidebar">
		<div class="netz-workstation-sidebar">
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
							<ChevronRight
								size={12}
								strokeWidth={2}
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
										<span class="nav-icon"><Icon size={18} strokeWidth={1.5} /></span>
										<span class="nav-label">{item.label}</span>
									</a>
								{/each}
							</nav>
						</div>
					{:else}
						<!-- Collapsed: divider between sections, icon-only items -->
						{#if section.id !== "discovery"}
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
									<span class="nav-icon"><Icon size={18} strokeWidth={1.5} /></span>
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
	<header class="netz-topbar">
		<div class="netz-topbar-brand">
			<span class="netz-topbar-logo">W</span>
			{#if !sidebarCollapsed}
				<span class="netz-topbar-appname">Wealth OS</span>
			{/if}
		</div>
		<div class="netz-topbar-divider"></div>

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

	<main class="netz-shell-main">
		<div class="netz-shell-content">
			{@render children()}
		</div>
	</main>
</div>

<style>
	/* ── Shell grid — topbar spans full width, sidebar+content below ── */
	.netz-shell {
		display: grid;
		grid-template-columns: var(--sidebar-w) 1fr;
		grid-template-rows: 58px 1fr;
		height: 100vh;
		width: 100vw;
		overflow: hidden;
		transition: grid-template-columns 200ms var(--netz-ease-out, cubic-bezier(0,0,.2,1));
	}

	.netz-shell-sidebar {
		grid-column: 1;
		grid-row: 2;
		overflow-y: auto;
		overflow-x: hidden;
		border-right: 1px solid var(--netz-border-subtle);
		transition: width 200ms var(--netz-ease-out, cubic-bezier(0,0,.2,1));
	}

	.netz-shell-main {
		grid-column: 2;
		grid-row: 2;
		overflow: hidden;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}

	/* ── Top Bar — spans BOTH columns (full width) ── */
	.netz-topbar {
		grid-column: 1 / -1;
		grid-row: 1;
		display: flex;
		align-items: center;
		gap: 0;
		height: 58px;
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-elevated);
		flex-shrink: 0;
		overflow: hidden;
	}

	/* ── Topbar brand section — aligns with sidebar width ── */
	.netz-topbar-brand {
		display: flex;
		align-items: center;
		gap: 9px;
		width: var(--sidebar-w);
		min-width: var(--sidebar-w);
		max-width: var(--sidebar-w);
		padding: 0 14px;
		flex-shrink: 0;
		overflow: hidden;
		transition: width 200ms var(--netz-ease-out, cubic-bezier(0,0,.2,1)),
		            min-width 200ms var(--netz-ease-out, cubic-bezier(0,0,.2,1));
	}

	.netz-topbar-logo {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 26px;
		height: 26px;
		border-radius: var(--netz-radius-md, 6px);
		background: var(--netz-brand-primary);
		color: #fff;
		font-size: 13px;
		font-weight: 700;
		flex-shrink: 0;
		font-family: var(--netz-font-sans);
	}

	.netz-topbar-appname {
		font-size: 15px;
		font-weight: 600;
		color: var(--netz-text-secondary);
		white-space: nowrap;
		overflow: hidden;
		font-family: var(--netz-font-sans);
	}

	/* Vertical divider between brand and search */
	.netz-topbar-divider {
		width: 1px;
		height: 20px;
		background: var(--netz-border-subtle);
		flex-shrink: 0;
		margin: 0 16px 0 0;
	}

	.netz-topbar-search {
		display: flex;
		align-items: center;
		gap: 6px;
		height: 32px;
		padding: 0 10px;
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-md, 6px);
		background: var(--netz-bg, var(--netz-surface));
		cursor: pointer;
		transition: border-color 120ms ease;
		min-width: 200px;
		max-width: 320px;
	}

	.netz-topbar-search:hover { border-color: var(--netz-border-focus); }

	.netz-topbar-search :global(.netz-topbar-search-icon) {
		color: var(--netz-text-muted); flex-shrink: 0;
	}

	.netz-topbar-search-input {
		flex: 1; border: none; background: transparent;
		color: var(--netz-text-muted); font-size: 0.8125rem;
		font-family: var(--netz-font-sans); cursor: pointer; outline: none;
	}

	.netz-topbar-kbd {
		display: inline-flex; align-items: center; justify-content: center;
		min-width: 20px; height: 20px; padding: 0 5px;
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-xs, 4px);
		background: var(--netz-surface-alt);
		color: var(--netz-text-muted); font-size: 11px;
		font-family: var(--netz-font-mono); font-weight: 500; line-height: 1;
	}

	.netz-topbar-actions {
		display: flex; align-items: center; gap: 6px;
		margin-left: auto;
		padding-right: 16px;
	}

	.netz-topbar-btn {
		display: flex; align-items: center; justify-content: center;
		width: 32px; height: 32px;
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-md, 6px);
		background: transparent; color: var(--netz-text-secondary);
		cursor: pointer;
		transition: color 120ms ease, background-color 120ms ease, border-color 120ms ease;
	}

	.netz-topbar-btn:hover { color: var(--netz-text-primary); background: var(--netz-surface-alt); }

	.netz-topbar-btn--ai { border-color: var(--netz-brand-highlight); color: var(--netz-brand-highlight); }
	.netz-topbar-btn--ai:hover {
		background: color-mix(in srgb, var(--netz-brand-highlight) 10%, transparent);
		color: var(--netz-brand-highlight);
	}

	/* ── Scrollable content area — TC: same bg as sidebar, 48px horiz padding ── */
	.netz-shell-content {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		padding: 0 48px;
		background: var(--netz-bg, #f5f8fd);
	}

	@media (max-width: 767px) {
		.netz-shell-content {
			padding: 0 16px;
		}
	}

	/* ── Sidebar container — TC: no border, separation by bg only ── */
	.netz-workstation-sidebar {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--netz-surface-alt);
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
		scrollbar-color: var(--netz-border) transparent;
	}

	/* ── Section header — clickable ── */
	.section-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: 6px 8px;
		margin-top: 20px;
		margin-bottom: 8px;
		border: none;
		background: transparent;
		cursor: pointer;
		user-select: none;
	}

	.section-header:first-child {
		margin-top: 8px;
	}

	.section-label {
		font-size: 14px;
		font-weight: 600;
		color: var(--netz-text-primary);
	}

	.section-header :global(.section-chevron) {
		color: var(--netz-text-muted);
		transition: transform 200ms var(--netz-ease-out, cubic-bezier(0,0,.2,1));
		flex-shrink: 0;
	}

	.section-header :global(.section-chevron.open) {
		transform: rotate(90deg);
	}

	/* ── Accordion — grid trick (no height hacks) ── */
	.section-items {
		display: grid;
		grid-template-rows: 0fr;
		overflow: hidden;
		transition: grid-template-rows 220ms var(--netz-ease-out, cubic-bezier(0,0,.2,1));
	}

	.section-items.open {
		grid-template-rows: 1fr;
	}

	.section-items-inner {
		min-height: 0;
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: 2px 8px 4px;
		margin-left: 12px;
		position: relative;
	}

	.section-items-inner::before {
		content: "";
		position: absolute;
		left: 0;
		top: 4px;
		bottom: 4px;
		width: 1px;
		background: var(--netz-border-subtle, #e5e7eb);
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
		border-top: 1px solid var(--netz-border-subtle);
	}

	/* ── Nav item — TC: 15.2px, 4px radius, #e0efff active, #f3f4f6 hover ── */
	.nav-item {
		display: flex;
		align-items: center;
		gap: 9px;
		padding: 6px 8px;
		border-radius: var(--netz-radius-sm, 4px);
		color: var(--netz-text-muted);
		font-size: 0.95rem;
		font-weight: 500;
		line-height: 21.7px;
		transition: background 120ms ease, color 120ms ease;
		text-decoration: none;
		white-space: nowrap;
	}

	.nav-item:hover {
		background: var(--netz-bg-hover, #f3f4f6);
		color: var(--netz-text-primary);
	}

	.nav-item.active {
		background: var(--netz-surface-highlight, #e0efff);
		color: var(--netz-text-secondary);
		font-weight: 600;
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
		border-top: 1px solid var(--netz-border-subtle);
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
		border-radius: var(--netz-radius-md, 6px);
		background: transparent;
		color: var(--netz-text-muted);
		cursor: pointer;
		transition: color 120ms ease, background-color 120ms ease;
	}

	.sidebar-toggle:hover {
		color: var(--netz-text-primary);
		background: color-mix(in srgb, var(--netz-brand-primary) 8%, transparent);
	}

	.sidebar-toggle-icon {
		transition: transform 200ms var(--netz-ease-out, cubic-bezier(0,0,.2,1));
	}

	.sidebar-toggle-icon.rotated {
		transform: rotate(180deg);
	}
</style>
