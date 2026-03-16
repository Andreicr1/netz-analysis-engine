<!--
  Root layout — AppShell with Sidebar, branding injection, session expiry monitor.
-->
<script lang="ts">
	import "../app.css";
	import { page } from "$app/stores";
	import { AppShell, Sidebar, ErrorBoundary, Toast } from "@netz/ui";
	import { brandingToCSS, startSessionExpiryMonitor, setConflictHandler, setAuthRedirectHandler } from "@netz/ui/utils";
	import type { NavItem } from "@netz/ui/utils";
	import { goto, invalidateAll } from "$app/navigation";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

	let sidebarCollapsed = $state(false);
	let showExpiryWarning = $state(false);
	let conflictMessage = $state<string | null>(null);

	// Branding CSS injection
	let brandingCSS = $derived(brandingToCSS(data.branding));

	// Navigation items
	const navItems: NavItem[] = [
		{ label: "Dashboard", href: "/dashboard", icon: "\u{1F4CA}" },
		{ label: "Pipeline", href: "/pipeline", icon: "\u{1F4C8}" },
		{ label: "Portfolio", href: "/portfolio", icon: "\u{1F4BC}" },
		{ label: "Documents", href: "/documents", icon: "\u{1F4C4}" },
		{ label: "Reporting", href: "/reporting", icon: "\u{1F4D1}" },
		{ label: "Copilot", href: "/copilot", icon: "\u{1F916}" },
	];

	// Session expiry monitor
	$effect(() => {
		if (data.token && data.token !== "dev-token") {
			const cleanup = startSessionExpiryMonitor(data.token, () => {
				showExpiryWarning = true;
			});
			return cleanup;
		}
	});

	// Register 401 redirect handler
	$effect(() => {
		setAuthRedirectHandler(() => goto("/auth/sign-in"));
		setConflictHandler((msg) => {
			conflictMessage = msg;
			invalidateAll();
			setTimeout(() => { conflictMessage = null; }, 4000);
		});
	});
</script>

<svelte:head>
	{@html `<style>:root { ${brandingCSS} }</style>`}
</svelte:head>

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
							{#if data.branding.logo_light_url}
								<img
									src={data.branding.logo_light_url}
									alt={data.branding.org_name}
									class="h-8 w-auto"
								/>
							{:else}
								<span class="text-lg font-bold text-[var(--netz-navy)]">Netz Credit</span>
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
