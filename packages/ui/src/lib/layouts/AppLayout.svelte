<!--
  @component AppLayout
  Shared root layout: AppShell + Sidebar, branding injection, session expiry, conflict toast.
  Used by both credit and wealth frontends.
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { AppShell, Sidebar, ErrorBoundary, Toast } from "../index.js";
	import { injectBranding, startSessionExpiryMonitor, setConflictHandler, setAuthRedirectHandler } from "../utils/index.js";
	import type { NavItem, BrandingConfig } from "../utils/types.js";
	import { goto, invalidateAll } from "$app/navigation";
	import { setContext } from "svelte";
	import type { Snippet } from "svelte";

	let {
		navItems,
		appName,
		branding,
		token,
		children,
	}: {
		navItems: NavItem[];
		appName: string;
		branding: BrandingConfig;
		token: string;
		children: Snippet;
	} = $props();

	let sidebarCollapsed = $state(false);
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
	<AppShell {sidebarCollapsed}>
		{#snippet sidebar()}
			<Sidebar
				items={navItems}
				collapsed={sidebarCollapsed}
				onToggle={() => sidebarCollapsed = !sidebarCollapsed}
				activeHref={$page.url.pathname}
			>
				{#snippet header()}
					{#if !sidebarCollapsed}
						<div class="flex items-center gap-2 px-2">
							{#if branding.logo_light_url}
								<img
									src={branding.logo_light_url}
									alt={branding.org_name}
									class="h-8 w-auto"
								/>
							{:else}
								<span class="text-lg font-bold text-[var(--netz-navy)]">{appName}</span>
							{/if}
						</div>
					{:else}
						<div class="flex justify-center">
							<span class="text-lg font-bold text-[var(--netz-navy)]">N</span>
						</div>
					{/if}
				{/snippet}
			</Sidebar>
		{/snippet}

		{#snippet main()}
			{@render children()}
		{/snippet}
	</AppShell>
</ErrorBoundary>

{#if showExpiryWarning}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
		<div class="mx-4 w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
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
					class="rounded-md bg-[var(--netz-primary)] px-4 py-2 text-sm font-medium text-white hover:opacity-90"
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
