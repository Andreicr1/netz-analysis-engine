<!--
  Root layout — auth context, branding injection, session expiry.
  Navigation is handled by (app)/+layout.svelte via AppShell + Sidebar.
-->
<script lang="ts">
	import "../app.css";
	import { invalidateAll } from "$app/navigation";
	import { setContext } from "svelte";
	import { ErrorBoundary, Toast } from "@investintell/ui";
	import { injectBranding, setConflictHandler, setAuthRedirectHandler } from "@investintell/ui/utils";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

	let conflictMessage = $state<string | null>(null);

	// Auth context — provides getToken to child components.
	// Token comes from server-side cookie verification only.
	setContext("netz:getToken", () => Promise.resolve(data.token));

	// Branding CSS injection
	$effect(() => {
		if (typeof document !== "undefined" && data.branding) {
			injectBranding(document.documentElement, data.branding);
		}
	});

	// 401 redirect + conflict handler (with loop guard)
	$effect(() => {
		setAuthRedirectHandler(() => {
			// Prevent redirect loop: if page just loaded, don't redirect immediately
			const pageLoadTime = performance.now();
			if (pageLoadTime < 3000) {
				console.warn("Auth redirect suppressed — page just loaded (possible 401 loop)");
				return;
			}
			// In dev mode, just reload to re-trigger server-side dev bypass
			if (import.meta.env.DEV) {
				window.location.reload();
				return;
			}
			window.location.href = "https://accounts.investintell.com/sign-in?redirect_url=" + encodeURIComponent("https://wealth.investintell.com/auth/callback");
		});
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

{#if conflictMessage}
	<Toast message={conflictMessage} type="warning" duration={4000} onDismiss={() => conflictMessage = null} />
{/if}
