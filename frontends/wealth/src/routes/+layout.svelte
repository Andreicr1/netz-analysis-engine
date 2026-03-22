<!--
  Root layout — auth context, branding injection, session expiry.
  Navigation is handled by (app)/+layout.svelte via AppShell + Sidebar.
-->
<script lang="ts">
	import "../app.css";
	import { page } from "$app/stores";
	import { goto, invalidateAll } from "$app/navigation";
	import { setContext } from "svelte";
	import { ErrorBoundary, Toast } from "@netz/ui";
	import { injectBranding, startSessionExpiryMonitor, setConflictHandler, setAuthRedirectHandler } from "@netz/ui/utils";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

	let showExpiryWarning = $state(false);
	let conflictMessage = $state<string | null>(null);

	// Auth context — provides getToken to child components
	setContext("netz:getToken", () => Promise.resolve(data.token));

	// Branding CSS injection
	$effect(() => {
		if (typeof document !== "undefined" && data.branding) {
			injectBranding(document.documentElement, data.branding);
		}
	});

	// Session expiry monitor
	$effect(() => {
		if (data.token && data.token !== "dev-token") {
			const cleanup = startSessionExpiryMonitor(data.token, () => {
				showExpiryWarning = true;
			});
			return cleanup;
		}
	});

	// 401 redirect + conflict handler
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
	{@render children()}
</ErrorBoundary>

{#if showExpiryWarning}
	<div class="fixed inset-0 z-50 flex items-center justify-center" style="background: var(--netz-surface-overlay, rgba(0,0,0,0.5))">
		<div class="mx-4 w-full max-w-md rounded-lg bg-(--netz-surface-elevated) p-6 shadow-xl">
			<h2 class="mb-2 text-lg font-semibold text-(--netz-text-primary)">Session Expiring</h2>
			<p class="mb-4 text-sm text-(--netz-text-secondary)">
				Your session expires in 5 minutes. Please save your work and renew your access.
			</p>
			<div class="flex justify-end gap-3">
				<button
					class="rounded-md px-4 py-2 text-sm font-medium text-(--netz-text-secondary) hover:bg-(--netz-surface-alt)"
					onclick={() => showExpiryWarning = false}
				>
					Dismiss
				</button>
				<button
					class="rounded-md bg-(--netz-brand-primary) px-4 py-2 text-sm font-medium text-white hover:opacity-90"
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
