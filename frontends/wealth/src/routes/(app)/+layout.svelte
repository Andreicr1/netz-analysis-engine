<!--
  App layout — InvestIntell Workstation.
  Plain flex layout: aside sidebar + right column (topbar + content panel with black breathing room).
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { afterNavigate } from "$app/navigation";
	import { onMount, setContext, getContext, type Snippet } from "svelte";
	import { createRiskStore, type RiskStore } from "$lib/stores/risk-store.svelte";
	import { createMarketDataStore, type MarketDataStore } from "$lib/stores/market-data.svelte";
	import { createPortfolioAnalytics, type PortfolioAnalyticsStore } from "$lib/stores/portfolio-analytics.svelte";
	import AiAgentDrawer from "$lib/components/AiAgentDrawer.svelte";
	import GlobalSearch from "$lib/components/GlobalSearch.svelte";
	import ThemeToggle from "$lib/components/ThemeToggle.svelte";
	import GlobalAlertInbox from "$lib/components/GlobalAlertInbox.svelte";
	import {
		LayoutDashboard, FileSearch, Table2, Library, Globe,
		Settings, Menu, Cpu, Mic, Compass,
	} from "lucide-svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	let { children }: { children: Snippet } = $props();

	let agentOpen = $state(false);
	let searchOpen = $state(false);
	let sidebarOpen = $state(true);

	// ── Welcome banner lifecycle ──────────────────────────────────────
	// Visible on the first layout mount; auto-fades after 10s (2s
	// transition) OR the moment the user navigates to a new page for
	// the first time — whichever comes first. After that, stays hidden
	// for the rest of the session so institutional users are never
	// greeted twice.
	let welcomeVisible = $state(true);
	let welcomeHiding = $state(false);
	let firstNavSkipped = false;
	let welcomeTimer: ReturnType<typeof setTimeout> | null = null;
	let welcomeUnmountTimer: ReturnType<typeof setTimeout> | null = null;

	function dismissWelcome() {
		if (!welcomeVisible || welcomeHiding) return;
		welcomeHiding = true;
		if (welcomeTimer) clearTimeout(welcomeTimer);
		welcomeTimer = null;
		// Allow the 2s opacity transition to finish before unmounting.
		welcomeUnmountTimer = setTimeout(() => {
			welcomeVisible = false;
			welcomeHiding = false;
		}, 2000);
	}

	afterNavigate(() => {
		// The first `afterNavigate` fires on the initial load — ignore
		// it. The second fire is the user's first real navigation.
		if (!firstNavSkipped) {
			firstNavSkipped = true;
			return;
		}
		dismissWelcome();
	});

	const riskStore = createRiskStore({
		profileIds: ["conservative", "moderate", "growth"],
		getToken,
		pollingFallbackMs: 30_000,
	});
	setContext<RiskStore>("netz:riskStore", riskStore);

	const marketStore = createMarketDataStore({ getToken });
	setContext<MarketDataStore>("netz:marketDataStore", marketStore);

	const portfolioAnalytics = createPortfolioAnalytics(marketStore);
	setContext<PortfolioAnalyticsStore>("netz:portfolioAnalytics", portfolioAnalytics);

	// Risk store lifecycle — SSE connects once at layout level, persists across navigations.
	// Market data store — WebSocket connects once, persists across navigations.
	onMount(() => {
		riskStore.start(true);
		marketStore.start();
		// Start the 10-second welcome auto-dismiss clock.
		welcomeTimer = setTimeout(dismissWelcome, 10_000);
		return () => {
			riskStore.destroy();
			marketStore.stop();
			if (welcomeTimer) clearTimeout(welcomeTimer);
			if (welcomeUnmountTimer) clearTimeout(welcomeUnmountTimer);
		};
	});

	const navItems = [
		{ label: "Dashboard", href: "/dashboard",         icon: LayoutDashboard },
		{ label: "Discovery", href: "/discovery",         icon: Compass },
		{ label: "Screener",  href: "/screener",          icon: FileSearch },
		{ label: "Portfolio", href: "/portfolio",         icon: Table2 },
		{ label: "Library",   href: "/library",           icon: Library },
		{ label: "Market",    href: "/market",            icon: Globe },
	];

	function isActive(href: string): boolean {
		return $page.url.pathname === href || $page.url.pathname.startsWith(href + "/");
	}

	// ── Full-bleed route opt-out ─────────────────────────────────
	// Most content routes benefit from the max-w-screen-2xl cap +
	// p-6 padding for readability. Workspace-class routes like
	// /portfolio (Flexible Columns Layout Builder) need every
	// horizontal pixel — the 12-column Universe table alone demands
	// ~1074px, and at 45% of workspace that requires > 2000px of
	// canvas. Those routes opt out of the cage here.
	const FULL_BLEED_PATHS = ["/portfolio", "/discovery"];
	const isFullBleed = $derived(
		FULL_BLEED_PATHS.some(
			(p) => $page.url.pathname === p || $page.url.pathname.startsWith(p + "/"),
		),
	);
</script>

<div class="flex h-screen w-full bg-[var(--ii-bg)] text-[var(--ii-text-primary)] overflow-hidden font-sans">

	<!-- ── Sidebar ── -->
	{#if sidebarOpen}
		<aside class="w-[240px] flex-shrink-0 flex flex-col bg-[var(--ii-bg)] h-full transition-all duration-300">

			<!-- Hamburger — same row height as TopNav, aligned with nav icons -->
			<div class="h-[72px] flex items-center px-6">
				<button
					type="button"
					class="text-[var(--ii-text-primary)] hover:bg-[var(--ii-surface-highlight)] size-10 rounded-full flex items-center justify-center shrink-0 -ml-2"
					onclick={() => sidebarOpen = false}
					aria-label="Close sidebar"
				>
					<Menu size={24} />
				</button>
			</div>

			<!-- Welcome banner — shown once per session, fades out -->
			{#if welcomeVisible}
				<div
					class="welcome-banner px-6 pb-4"
					class:welcome-hiding={welcomeHiding}
					aria-hidden={welcomeHiding}
				>
					<p class="text-2xl leading-tight">
						<span class="font-normal text-[var(--ii-text-muted)]">Welcome,</span><br />
						<span class="font-semibold text-[var(--ii-text-primary)]">User</span>
					</p>
				</div>

				<div
					class="welcome-divider mx-6 mt-4 mb-3 border-t border-[var(--ii-border-subtle)]"
					class:welcome-hiding={welcomeHiding}
				></div>
			{/if}

			<!-- Navigation block — flex-1 to push logo down -->
			<nav class="px-4 flex-1 flex flex-col overflow-y-auto">
				<p class="px-4 mb-3 text-[11px] font-normal tracking-[2px] uppercase text-[var(--ii-text-secondary)]">
					Main Menu
				</p>
				<ul class="space-y-0">
					{#each navItems as item (item.href)}
						{@const Icon = item.icon}
						{@const active = isActive(item.href)}
						<li>
							<a
								href={item.href}
								aria-current={active ? "page" : undefined}
								style:text-decoration="none"
								class="flex items-center gap-3 px-4 h-11 rounded-[4px] text-[15px] transition-colors
									{active
										? 'bg-[#0177fb] text-white font-semibold'
										: 'text-[var(--ii-text-primary)] font-normal hover:bg-[var(--ii-surface-highlight)]'
									}"
							>
								<Icon size={20} />
								<span>{item.label}</span>
							</a>
						</li>
					{/each}
				</ul>

				<!-- System — pushed to bottom of nav, with margin below -->
				<div class="mt-auto mb-12">
					<p class="px-4 mb-3 text-[11px] font-normal tracking-[2px] uppercase text-[var(--ii-text-secondary)]">
						System
					</p>
					<a
						href="/settings"
						style:text-decoration="none"
						class="flex items-center gap-3 px-4 h-11 rounded-[4px] text-[15px] transition-colors
							{isActive('/settings')
								? 'bg-[#0177fb] text-white font-semibold'
								: 'text-[var(--ii-text-primary)] font-normal hover:bg-[var(--ii-surface-highlight)]'
							}"
					>
						<Settings size={20} />
						<span>Settings</span>
					</a>
				</div>
			</nav>

			<!-- Logo — anchored to bottom with generous spacing -->
			<div class="mt-auto px-6 pb-6">
				<div class="flex items-center gap-2.5">
					<svg width="32" height="38" viewBox="0 0 20 24" fill="none" xmlns="http://www.w3.org/2000/svg">
						<circle cx="4" cy="4" r="1.5" fill="#0177fb" /><circle cx="10" cy="4" r="1.5" fill="#0177fb" />
						<circle cx="16" cy="4" r="1.5" fill="#0177fb" /><circle cx="10" cy="12" r="2" fill="#0177fb" />
						<circle cx="4" cy="20" r="1.5" fill="#888" /><circle cx="10" cy="20" r="1.5" fill="#888" /><circle cx="16" cy="20" r="1.5" fill="#888" />
						<line x1="4" y1="4" x2="10" y2="12" stroke="#0177fb" stroke-width="1" stroke-linecap="round" />
						<line x1="16" y1="4" x2="10" y2="12" stroke="#0177fb" stroke-width="1" stroke-linecap="round" />
						<line x1="4" y1="20" x2="10" y2="12" stroke="#888" stroke-width="1" stroke-linecap="round" />
						<line x1="16" y1="20" x2="10" y2="12" stroke="#888" stroke-width="1" stroke-linecap="round" />
					</svg>
					<span class="text-[22px] tracking-tight whitespace-nowrap">
						<span class="font-normal text-[var(--ii-text-primary)]">invest</span><span class="font-bold text-[#2563eb]">intell</span>
					</span>
				</div>
			</div>
		</aside>
	{/if}

	<!-- ── Right column: TopNav + Content ── -->
	<div class="flex flex-1 flex-col h-full min-w-0 bg-[var(--ii-bg)]">

		<!-- TopNav -->
		<header class="h-[72px] flex-shrink-0 bg-[var(--ii-bg)] flex items-center px-6 py-3 gap-4">
			{#if !sidebarOpen}
				<button
					type="button"
					class="text-[var(--ii-text-primary)] hover:bg-[var(--ii-surface-highlight)] size-10 rounded-full flex items-center justify-center shrink-0"
					onclick={() => sidebarOpen = true}
					aria-label="Open sidebar"
				>
					<Menu size={24} />
				</button>
			{/if}

			<div class="flex-1"></div>

			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div
				class="flex items-center gap-2.5 pl-5 pr-14 h-10 rounded-full bg-[var(--ii-surface-elevated)] border border-[var(--ii-border-subtle)] cursor-pointer hover:bg-[var(--ii-surface-raised)] transition-colors max-w-md w-full"
				onclick={() => searchOpen = true}
			>
				<Mic size={16} class="text-[var(--ii-text-muted)] shrink-0" />
				<span class="text-[var(--ii-text-muted)] text-sm whitespace-nowrap">Ask InvestIntell anything</span>
				<span class="ml-auto text-[10px] font-mono text-[var(--ii-text-muted)] border border-[var(--ii-border)] rounded px-1.5 py-0.5 leading-none">Ctrl K</span>
			</div>

			<div class="flex-1"></div>

			<div class="flex items-center gap-3 shrink-0">
				<!-- Theme toggle + Bell + CPU -->
				<div class="flex items-center gap-1.5">
					<ThemeToggle />
					<!--
					  Phase 7 Alerts Unification — the Phase 0 dead Bell
					  stub is replaced with the global inbox component
					  which owns its own bell icon + dropdown + workspace
					  polling lifecycle.
					-->
					<GlobalAlertInbox />
					<button type="button" class="rounded-full bg-[var(--ii-surface-elevated)] hover:bg-[var(--ii-surface-raised)] p-2.5 flex items-center justify-center transition-colors border border-[var(--ii-border-subtle)]" onclick={() => agentOpen = !agentOpen} aria-label="AI assistant">
						<Cpu size={18} class="text-[var(--ii-text-primary)]" />
					</button>
				</div>
				<!-- Avatar + name -->
				<div class="flex items-center gap-2.5">
					<div class="size-10 rounded-full bg-gradient-to-br from-[#0177fb] to-[#6366f1] flex items-center justify-center text-white text-sm font-semibold shrink-0">U</div>
					<div class="flex flex-col gap-0.5 leading-tight">
						<span class="text-sm text-[var(--ii-text-primary)]">User l</span>
						<span class="text-xs font-light text-[var(--ii-text-primary)]">e-mail</span>
					</div>
				</div>
			</div>
		</header>

		<!-- Content panel — calc() height locks the box, padding creates black margins -->
		<div
			class="bg-[var(--ii-bg)] overflow-hidden"
			style="height: calc(100vh - 72px); padding: 0 24px 24px 0;"
		>
			<main class="w-full h-full bg-[var(--ii-surface-elevated)] rounded-tl-[32px] shadow-2xl border border-[var(--ii-border-subtle)] flex flex-col overflow-hidden">
				{#if isFullBleed}
					<!-- Full-bleed: no padding, no max-width cap. Child owns geometry. -->
					<div class="flex-1 min-h-0 overflow-hidden">
						{@render children()}
					</div>
				{:else}
					<div class="flex-1 min-h-0 overflow-y-auto p-6">
						<div class="mx-auto w-full max-w-screen-2xl">
							{@render children()}
						</div>
					</div>
				{/if}
			</main>
		</div>
	</div>
</div>

<AiAgentDrawer open={agentOpen} onclose={() => agentOpen = false} />
<GlobalSearch bind:open={searchOpen} />

<style>
	.welcome-banner,
	.welcome-divider {
		opacity: 1;
		transform: translateY(0);
		transition:
			opacity 2000ms ease-out,
			transform 2000ms ease-out;
		will-change: opacity, transform;
	}

	.welcome-banner.welcome-hiding,
	.welcome-divider.welcome-hiding {
		opacity: 0;
		transform: translateY(-6px);
		pointer-events: none;
	}
</style>
