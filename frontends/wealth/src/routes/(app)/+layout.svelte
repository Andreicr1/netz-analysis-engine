<!--
  App layout — InvestIntell Workstation.
  Plain flex layout: aside sidebar + right column (topbar + content panel with black breathing room).
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { onMount, setContext, getContext, type Snippet } from "svelte";
	import { createRiskStore, type RiskStore } from "$lib/stores/risk-store.svelte";
	import AiAgentDrawer from "$lib/components/AiAgentDrawer.svelte";
	import GlobalSearch from "$lib/components/GlobalSearch.svelte";
	import {
		LayoutDashboard, FileSearch, Table2, Axis3d, Globe,
		Settings, Menu, Bell, Cpu, Mic,
	} from "lucide-svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	let { children }: { children: Snippet } = $props();

	let agentOpen = $state(false);
	let searchOpen = $state(false);
	let sidebarOpen = $state(true);

	const riskStore = createRiskStore({
		profileIds: ["conservative", "moderate", "growth"],
		getToken,
		pollingFallbackMs: 30_000,
	});
	setContext<RiskStore>("netz:riskStore", riskStore);

	// Risk store lifecycle — SSE connects once at layout level, persists across navigations.
	// Pages with SSR risk data call seedFromSSR() to populate immediately.
	onMount(() => {
		riskStore.start(true);
		return () => riskStore.destroy();
	});

	const navItems = [
		{ label: "Dashboard", href: "/dashboard",         icon: LayoutDashboard },
		{ label: "Screener",  href: "/screener",          icon: FileSearch },
		{ label: "Portfolio", href: "/portfolio/approved", icon: Table2 },
		{ label: "Analysis",  href: "/analysis",          icon: Axis3d },
		{ label: "Market",    href: "/market",            icon: Globe },
	];

	function isActive(href: string): boolean {
		return $page.url.pathname === href || $page.url.pathname.startsWith(href + "/");
	}
</script>

<div class="flex h-screen w-full bg-black text-white overflow-hidden font-sans">

	<!-- ── Sidebar ── -->
	{#if sidebarOpen}
		<aside class="w-[300px] flex-shrink-0 flex flex-col bg-black h-full transition-all duration-300">

			<!-- Hamburger — same row height as TopNav, aligned with nav icons -->
			<div class="h-[88px] flex items-center px-[50px]">
				<button
					type="button"
					class="text-white hover:bg-white/10 size-10 rounded-full flex items-center justify-center shrink-0 -ml-2"
					onclick={() => sidebarOpen = false}
					aria-label="Close sidebar"
				>
					<Menu size={24} />
				</button>
			</div>

			<!-- Welcome -->
			<div class="px-[50px] pb-4">
				<p class="text-[32px] leading-tight">
					<span class="font-normal text-[#85a0bd]">Welcome,</span><br />
					<span class="font-semibold text-white">User</span>
				</p>
			</div>

			<div class="mx-[27px] mt-6 mb-4 border-t border-[#404249]"></div>

			<!-- Navigation block — flex-1 to push logo down -->
			<nav class="px-[27px] flex-1 flex flex-col overflow-y-auto">
				<p class="px-[23px] mb-3 text-[12px] font-normal tracking-[2px] uppercase text-[#d9d9d9]">
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
								style:color="white"
								style:text-decoration="none"
								class="flex items-center gap-4 px-[23px] h-[58px] rounded-[4px] text-[18px] transition-colors
									{active
										? 'bg-[#0177fb] font-semibold'
										: 'font-normal hover:bg-white/5'
									}"
							>
								<Icon size={24} />
								<span>{item.label}</span>
							</a>
						</li>
					{/each}
				</ul>

				<!-- System — pushed to bottom of nav, with margin below -->
				<div class="mt-auto mb-12">
					<p class="px-[23px] mb-3 text-[12px] font-normal tracking-[2px] uppercase text-[#d9d9d9]">
						System
					</p>
					<a
						href="/settings"
						style:color="white"
						style:text-decoration="none"
						class="flex items-center gap-4 px-[23px] h-[58px] rounded-[4px] text-[18px] font-normal hover:bg-white/5 transition-colors
							{isActive('/settings')
								? 'bg-[#0177fb] font-semibold'
								: ''
							}"
					>
						<Settings size={24} />
						<span>Settings</span>
					</a>
				</div>
			</nav>

			<!-- Logo — anchored to bottom with generous spacing -->
			<div class="mt-auto px-[50px] pb-8">
				<div class="flex items-center gap-3">
					<svg width="40" height="48" viewBox="0 0 20 24" fill="none" xmlns="http://www.w3.org/2000/svg">
						<circle cx="4" cy="4" r="1.5" fill="#0177fb" /><circle cx="10" cy="4" r="1.5" fill="#0177fb" />
						<circle cx="16" cy="4" r="1.5" fill="#0177fb" /><circle cx="10" cy="12" r="2" fill="#0177fb" />
						<circle cx="4" cy="20" r="1.5" fill="#888" /><circle cx="10" cy="20" r="1.5" fill="#888" /><circle cx="16" cy="20" r="1.5" fill="#888" />
						<line x1="4" y1="4" x2="10" y2="12" stroke="#0177fb" stroke-width="1" stroke-linecap="round" />
						<line x1="16" y1="4" x2="10" y2="12" stroke="#0177fb" stroke-width="1" stroke-linecap="round" />
						<line x1="4" y1="20" x2="10" y2="12" stroke="#888" stroke-width="1" stroke-linecap="round" />
						<line x1="16" y1="20" x2="10" y2="12" stroke="#888" stroke-width="1" stroke-linecap="round" />
					</svg>
					<span class="text-[27px] tracking-tight whitespace-nowrap">
						<span class="font-normal text-white">invest</span><span class="font-bold text-[#2563eb]">intell</span>
					</span>
				</div>
			</div>
		</aside>
	{/if}

	<!-- ── Right column: TopNav + Content ── -->
	<div class="flex flex-1 flex-col h-full min-w-0 bg-black">

		<!-- TopNav -->
		<header class="h-[88px] flex-shrink-0 bg-black flex items-center px-8 py-4 gap-6">
			{#if !sidebarOpen}
				<button
					type="button"
					class="text-white hover:bg-white/10 size-10 rounded-full flex items-center justify-center shrink-0"
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
				class="flex items-center gap-3 pl-6 pr-20 py-4 rounded-[35px] bg-[#1a1b20] cursor-pointer hover:bg-[#25262b] transition-colors max-w-[480px] w-full"
				onclick={() => searchOpen = true}
			>
				<Mic size={20} class="text-[#cbccd1] shrink-0" />
				<span class="text-[#cbccd1] text-[20px] whitespace-nowrap">Ask InvestIntell anything</span>
			</div>

			<div class="flex-1"></div>

			<div class="flex items-center gap-4 shrink-0">
				<!-- Bell + CPU: gap-0 between them -->
				<div class="flex items-center">
					<button type="button" class="rounded-full bg-[#1a1b20] p-4 flex items-center justify-center hover:bg-[#25262b] transition-colors" onclick={() => {}}>
						<Bell size={24} class="text-white" />
					</button>
					<button type="button" class="rounded-full bg-[#1a1b20] p-4 flex items-center justify-center hover:bg-[#25262b] transition-colors" onclick={() => agentOpen = !agentOpen}>
						<Cpu size={24} class="text-white" />
					</button>
				</div>
				<!-- Avatar + name -->
				<div class="flex items-center gap-3">
					<div class="size-[61px] rounded-full bg-gradient-to-br from-[#0177fb] to-[#6366f1] flex items-center justify-center text-white text-xl font-semibold shrink-0">U</div>
					<div class="flex flex-col gap-0.5 leading-tight">
						<span class="text-[18px] text-white">User l</span>
						<span class="text-[14px] font-light text-white">e-mail</span>
					</div>
				</div>
			</div>
		</header>

		<!-- Content panel — calc() height locks the box, padding creates black margins -->
		<div
			class="bg-black overflow-hidden"
			style="height: calc(100vh - 88px); padding: 34px;"
		>
			<main class="w-full h-full bg-[#1a1b20] rounded-tl-[32px] shadow-2xl border border-[#404149] overflow-hidden">
				<div class="h-full overflow-y-auto p-6">
					<div class="mx-auto w-full max-w-screen-2xl">
						{@render children()}
					</div>
				</div>
			</main>
		</div>
	</div>
</div>

<AiAgentDrawer open={agentOpen} onclose={() => agentOpen = false} />
<GlobalSearch bind:open={searchOpen} />
