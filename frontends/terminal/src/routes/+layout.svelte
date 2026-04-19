<!--
  Root layout — auth context + session expiry monitor.

  Scope note: X1 deliberately keeps this minimal — no TopNav, no sidebar,
  no ErrorBoundary Toast plumbing. The real shell (TerminalTopNav, focus
  mode chrome) lands in X2 when routes move over. This layout only does:
    1. Propagate `netz:getToken` so API clients in child routes can fetch.
    2. Wire branding (ii-bundle injection in X3 swaps the default).
    3. Start Clerk session expiry monitor once the token is known.

  Auth-pattern note: we intentionally do NOT use svelte-clerk's
  <SignedIn>/<SignedOut> gates. Wealth uses server-side gating via the
  createClerkHook in hooks.server.ts, and X1 mirrors that so both apps
  share one verified-JWT path. svelte-clerk is installed but only
  reserved for component-level UI (e.g. UserButton) in later sprints.
-->
<script lang="ts">
	import "../app.css";
	import { setContext } from "svelte";
	import { injectBranding, startSessionExpiryMonitor } from "@investintell/ui/utils";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

	// Auth context — provides getToken to child routes.
	setContext("netz:getToken", () => Promise.resolve(data.token));

	// Branding CSS injection (X3 swaps defaultDarkBranding for ii-bundle).
	$effect(() => {
		if (typeof document !== "undefined" && data.branding) {
			injectBranding(document.documentElement, data.branding);
		}
	});

	// Session expiry — client-only warning before Clerk token expiration.
	$effect(() => {
		if (typeof window === "undefined" || !data.token) return;
		const cleanup = startSessionExpiryMonitor(data.token, () => {
			console.warn("II Terminal session approaching expiry — refresh recommended.");
		});
		return cleanup;
	});
</script>

{@render children()}
