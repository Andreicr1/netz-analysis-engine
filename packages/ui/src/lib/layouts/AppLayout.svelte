<!--
  @component AppLayout
  Root layout: TopNav + optional ContextSidebar, branding injection, session expiry, conflict toast.
  Used by both credit and wealth frontends.

  Without contextNav: TopNav + main (100% width) — list pages, monitoring
  With contextNav: TopNav + ContextSidebar + main — detail pages ([fundId], [portfolioId])
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { ErrorBoundary, Toast } from "../index.js";
	import TopNav from "./TopNav.svelte";
	import ContextSidebar from "./ContextSidebar.svelte";
	import { injectBranding, startSessionExpiryMonitor, setConflictHandler, setAuthRedirectHandler } from "../utils/index.js";
	import type { NavItem, BrandingConfig, ContextNav } from "../utils/types.js";
	import { goto, invalidateAll } from "$app/navigation";
	import { setContext } from "svelte";
	import type { Snippet } from "svelte";

	let {
		navItems,
		appName,
		branding,
		token,
		contextNav,
		logo,
		trailing,
		children,
	}: {
		navItems: NavItem[];
		appName: string;
		branding: BrandingConfig;
		token: string;
		contextNav?: ContextNav;
		logo?: Snippet;
		trailing?: Snippet;
		children: Snippet;
	} = $props();

	let showExpiryWarning = $state(false);
	let conflictMessage = $state<string | null>(null);

	// Auth context — provides getToken to child components
	setContext("netz:getToken", () => Promise.resolve(token));

	// Branding CSS injection via DOM API (safe — setProperty auto-escapes values)
	$effect(() => {
		if (typeof document !== "undefined") {
			injectBranding(document.documentElement, branding);
		}
	});

	// Session expiry monitor
	$effect(() => {
		if (token && token !== "dev-token") {
			const cleanup = startSessionExpiryMonitor(token, () => {
				showExpiryWarning = true;
			});
			return cleanup;
		}
	});

	// Register 401 redirect handler
	$effect(() => {
		setAuthRedirectHandler(() => goto("/auth/sign-in"));
		setConflictHandler((msg: string) => {
			conflictMessage = msg;
			invalidateAll();
			setTimeout(() => { conflictMessage = null; }, 4000);
		});
	});
</script>

<ErrorBoundary>
	<div class="netz-app-layout">
		<TopNav
			items={navItems}
			{appName}
			activeHref={$page.url.pathname}
			{logo}
			{trailing}
		/>

		<div class="netz-app-layout__body">
			{#if contextNav}
				<ContextSidebar {contextNav} />
			{/if}

			<main class="netz-app-layout__main">
				{@render children()}
			</main>
		</div>
	</div>
</ErrorBoundary>

{#if showExpiryWarning}
	<div class="fixed inset-0 z-50 flex items-center justify-center" style="background: var(--netz-surface-overlay, rgba(0,0,0,0.5))">
		<div class="mx-4 w-full max-w-md rounded-lg bg-[var(--netz-surface-elevated)] p-6 shadow-xl">
			<h2 class="mb-2 text-lg font-semibold text-[var(--netz-text-primary)]">Session Expiring</h2>
			<p class="mb-4 text-sm text-[var(--netz-text-secondary)]">
				Your session expires in 5 minutes. Please save your work and renew your access.
			</p>
			<div class="flex justify-end gap-3">
				<button
					class="rounded-md px-4 py-2 text-sm font-medium text-[var(--netz-text-secondary)] hover:bg-[var(--netz-surface-alt)]"
					onclick={() => showExpiryWarning = false}
				>
					Dismiss
				</button>
				<button
					class="rounded-md bg-[var(--netz-brand-primary)] px-4 py-2 text-sm font-medium text-white hover:opacity-90"
					onclick={() => { showExpiryWarning = false; window.location.reload(); }}
				>
					Renew Session
				</button>
			</div>
		</div>
	</div>
{/if}

{#if conflictMessage}
	<Toast message={conflictMessage} type="warning" duration={4000} onDismiss={() => conflictMessage = null} />
{/if}

<style>
	.netz-app-layout {
		display: flex;
		flex-direction: column;
		height: 100vh;
		width: 100vw;
		overflow: hidden;
	}

	.netz-app-layout__body {
		display: flex;
		flex: 1;
		min-height: 0;
		overflow: hidden;
	}

	.netz-app-layout__main {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		background: var(--netz-surface-alt, #f9fafb);
		min-width: 0;
	}
</style>
