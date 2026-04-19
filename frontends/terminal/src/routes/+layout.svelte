<!--
  Root layout — auth context + terminal shell chrome.

  Scope note (X2): this layout merges X1's minimal auth/branding root
  with the (terminal) group layout that previously lived in wealth.
  Everything the Bloomberg-style workspace needs to boot now wires here:

    1. Propagate `netz:getToken` context so API clients in child routes
       can fetch with verified JWT.
    2. Inject tenant branding via `injectBranding()` (X3 swaps the
       default for ii-bundle tokens).
    3. Start Clerk session expiry monitor once the token is known.
    4. Create a terminal-scoped MarketDataStore under
       TERMINAL_MARKET_DATA_KEY — isolated from wealth's (app)
       dashboard store (separate WebSocket connection).
    5. Create TerminalTweaks (density / accent / theme) under
       TERMINAL_TWEAKS_KEY — in-memory, session-scoped.
    6. Render <TerminalShell> as the global chrome wrapper.

  Auth-pattern note: we intentionally do NOT use svelte-clerk's
  <SignedIn>/<SignedOut> gates. Wealth uses server-side gating via
  createClerkHook in hooks.server.ts, and terminal mirrors that so
  both apps share one verified-JWT path. svelte-clerk is installed
  but only reserved for component-level UI (e.g. UserButton) in
  later sprints.

  Component imports during X2 resolve through the transitional
  `$wealth/*` alias (see tsconfig.json, vite.config.ts, svelte.config.js).
  X5 promotes these to `@investintell/ii-terminal-core` and drops the
  alias entirely.
-->
<script lang="ts">
	import "../app.css";
	import { getContext, setContext } from "svelte";
	import { injectBranding, startSessionExpiryMonitor } from "@investintell/ui/utils";
	import {
		createMarketDataStore,
		type MarketDataStore,
	} from "$wealth/stores/market-data.svelte";
	import { TERMINAL_MARKET_DATA_KEY } from "$wealth/components/portfolio/live/workbench-state";
	import TerminalShell from "$wealth/components/terminal/shell/TerminalShell.svelte";
	import {
		createTerminalTweaks,
		TERMINAL_TWEAKS_KEY,
		type TerminalTweaks,
	} from "$wealth/stores/terminal-tweaks.svelte";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

	// 1. Auth context — provides getToken to child routes and to the
	// MarketDataStore's WebSocket bootstrapper below.
	setContext("netz:getToken", () => Promise.resolve(data.token));
	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// 4. Terminal-scoped MarketDataStore — separate WS connection from
	// the (app) dashboard's store in wealth. Lives for the lifetime of
	// the terminal SPA session.
	const marketStore = createMarketDataStore({ getToken });
	setContext<MarketDataStore>(TERMINAL_MARKET_DATA_KEY, marketStore);

	// 5. Terminal runtime tweaks (density / accent / theme). In-memory,
	// session-scoped. Consumed by TerminalShell (data-attrs) and
	// TerminalTweaksPanel (UI controls).
	const tweaks = createTerminalTweaks();
	setContext<TerminalTweaks>(TERMINAL_TWEAKS_KEY, tweaks);

	// 2. Branding CSS injection (X3 swaps defaultDarkBranding for ii-bundle).
	$effect(() => {
		if (typeof document !== "undefined" && data.branding) {
			injectBranding(document.documentElement, data.branding);
		}
	});

	// 3. Session expiry — client-only warning before Clerk token expiration.
	$effect(() => {
		if (typeof window === "undefined" || !data.token) return;
		const cleanup = startSessionExpiryMonitor(data.token, () => {
			console.warn("II Terminal session approaching expiry — refresh recommended.");
		});
		return cleanup;
	});
</script>

<TerminalShell>
	{@render children()}
</TerminalShell>
