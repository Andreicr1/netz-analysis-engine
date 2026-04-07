<!--
  @component AppLayout
  Root layout: TopNav + optional ContextSidebar, branding injection, session expiry, conflict toast.
  Used by both credit and wealth frontends.

  Without contextNav: TopNav + main (100% width) — list pages, monitoring
  With contextNav: TopNav + ContextSidebar + main — detail pages ([fundId], [portfolioId])
-->
<script lang="ts">
	import { page } from "$app/stores";
	import ErrorBoundary from "../analytical/ErrorBoundary.svelte";
	import Toast from "../analytical/Toast.svelte";
	import TopNav from "./TopNav.svelte";
	import ContextSidebar from "./ContextSidebar.svelte";
	import { injectBranding, startSessionExpiryMonitor, setConflictHandler, setAuthRedirectHandler } from "../../utils/index.js";
	import type { NavItem, BrandingConfig, ContextNav } from "../../utils/types.js";
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
		trailing: trailingSnippet,
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
		if (typeof document !== "undefined" && branding) {
			injectBranding(document.documentElement, branding);
		}
	});

	// Session expiry monitor — only warn if token has > 10 min remaining.
	// Clerk tokens are short-lived (~1 min) and auto-renewed by Clerk JS.
	// Showing a warning for auto-renewed tokens is a false positive.
	$effect(() => {
		if (token && token !== "dev-token") {
			try {
				const parts = token.split(".");
				if (parts.length === 3) {
					const payload = JSON.parse(atob(parts[1]!.replace(/-/g, "+").replace(/_/g, "/")));
					const exp = payload.exp;
					// Only start monitor if token lives longer than 10 minutes from now
					// (i.e., not a short-lived Clerk session token)
					if (typeof exp === "number" && (exp * 1000) - Date.now() > 10 * 60 * 1000) {
						const cleanup = startSessionExpiryMonitor(token, () => {
							showExpiryWarning = true;
						});
						return cleanup;
					}
				}
			} catch {
				// Non-standard token — skip monitor
			}
		}
	});

	// Register 401 redirect handler
	$effect(() => {
		setAuthRedirectHandler(() => {
			window.location.href = "https://accounts.investintell.com/sign-in";
		});
		setConflictHandler((msg: string) => {
			conflictMessage = msg;
			invalidateAll();
			setTimeout(() => { conflictMessage = null; }, 4000);
		});
	});
</script>

<ErrorBoundary>
	<div class="flex h-screen w-screen bg-black overflow-hidden font-sans text-white">

		<!-- Sidebar -->
		{#if contextNav}
			<ContextSidebar {contextNav} />
		{/if}

		<!-- Right column: TopNav + Content -->
		<div class="flex flex-1 flex-col h-full overflow-hidden bg-black">

			<TopNav
				items={navItems}
				{appName}
				activeHref={$page.url.pathname}
				{logo}
			>
				{#snippet trailing()}
					{#if trailingSnippet}
						{@render trailingSnippet()}
					{/if}
				{/snippet}
			</TopNav>

			<!-- Content panel with black breathing room -->
			<div class="flex-1 flex overflow-hidden bg-black p-4 pb-6 pr-6">
				<main class="flex-1 bg-[#1a1b20] rounded-tl-[32px] rounded-br-[32px] overflow-y-auto p-8 shadow-2xl relative border border-white/5">
					<div class="mx-auto h-full max-w-screen-2xl">
						{@render children()}
					</div>
				</main>
			</div>
		</div>
	</div>
</ErrorBoundary>

{#if showExpiryWarning}
	<div class="fixed inset-0 z-50 flex items-center justify-center" style="background: var(--ii-surface-overlay, rgba(0,0,0,0.5))">
		<div class="mx-4 w-full max-w-md rounded-lg bg-(--ii-surface-elevated) p-6 shadow-xl">
			<h2 class="mb-2 text-lg font-semibold text-(--ii-text-primary)">Session Expiring</h2>
			<p class="mb-4 text-sm text-(--ii-text-secondary)">
				Your session expires in 5 minutes. Please save your work and renew your access.
			</p>
			<div class="flex justify-end gap-3">
				<button
					class="rounded-md px-4 py-2 text-sm font-medium text-(--ii-text-secondary) hover:bg-(--ii-surface-alt)"
					onclick={() => showExpiryWarning = false}
				>
					Dismiss
				</button>
				<button
					class="rounded-md bg-(--ii-brand-primary) px-4 py-2 text-sm font-medium text-white hover:opacity-90"
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

