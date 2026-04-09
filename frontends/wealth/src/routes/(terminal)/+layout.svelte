<!--
  (terminal) — full-screen Bloomberg-style layout group.

  Phase 2 Terminal Grid Shell. The Live Workbench and any future
  execution surfaces that must escape the SaaS chrome live under
  this route group. No topbar, no sidebar, no drawer.

  Inheritance chain:
    src/routes/+layout.server.ts   — hydrates ``actor`` + ``token``
    src/routes/+layout.svelte      — root layout (Clerk, fonts, theme,
                                     sets ``netz:getToken`` context)
    src/routes/(terminal)/+layout.svelte — THIS FILE
    src/routes/(terminal)/portfolio/live/+page.* — the terminal

  The root +layout.svelte is kept in the chain so Clerk context,
  fonts, theme tokens, and the base CSS reset still apply. Only the
  (app)/+layout.svelte with its sidebar/topbar/drawer stack is
  skipped.

  MarketDataStore isolation:
    The (app) layout creates its own MarketDataStore under the key
    "netz:marketDataStore". The terminal creates a SEPARATE instance
    under "netz:terminal:marketDataStore" so the two do not cross-
    contaminate subscriptions or WebSocket connections. Terminal pages
    use getContext(TERMINAL_MARKET_DATA_KEY) to access theirs.
-->
<script lang="ts">
	import type { Snippet } from "svelte";
	import { getContext, setContext } from "svelte";
	import {
		createMarketDataStore,
		type MarketDataStore,
	} from "$lib/stores/market-data.svelte";
	import { TERMINAL_MARKET_DATA_KEY } from "$lib/components/portfolio/live/workbench-state";

	let { children }: { children: Snippet } = $props();

	// Consume the Clerk token provider set by the root layout.
	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// Instantiate a terminal-scoped MarketDataStore. This is a
	// separate WS connection from the (app) dashboard's store —
	// the terminal manages its own subscriptions and lifecycle.
	const marketStore = createMarketDataStore({ getToken });
	setContext<MarketDataStore>(TERMINAL_MARKET_DATA_KEY, marketStore);
</script>

<div class="terminal-root">
	{@render children()}
</div>

<style>
	.terminal-root {
		/* Full-viewport lock — zero chrome inheritance.
		   100dvh accounts for mobile/OS chrome bars that
		   eat into 100vh on some platforms (Windows taskbar
		   at 125% zoom, iOS Safari bottom bar). */
		position: fixed;
		inset: 0;
		width: 100vw;
		height: 100dvh;
		overflow: hidden;
		background: #05080f;
		color: #ffffff;
		font-family: "Urbanist", system-ui, sans-serif;
		/* Isolate paint so transforms/filters inside the terminal
		   do not leak into the root stacking context. */
		isolation: isolate;
		z-index: 1;
	}

	/* Kill body scroll so nothing pushes past the terminal box. */
	:global(body:has(.terminal-root)) {
		overflow: hidden;
	}
</style>
