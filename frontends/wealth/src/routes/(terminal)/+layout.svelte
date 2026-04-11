<!--
  (terminal) — Bloomberg-style layout group.

  The chrome of every terminal surface is owned by TerminalShell
  (see lib/components/terminal/shell/TerminalShell.svelte). This
  layout file is now a minimal wrapper: it sets up the terminal-
  scoped MarketDataStore context consumed by live portfolio pages,
  then renders the shell with the route children as its snippet.

  Inheritance chain:
    src/routes/+layout.server.ts  — hydrates actor + token
    src/routes/+layout.svelte     — root layout (Clerk, fonts, theme,
                                    sets netz:getToken context)
    src/routes/(terminal)/+layout.svelte — THIS FILE
    src/routes/(terminal)/**/+page.svelte — terminal pages

  MarketDataStore isolation:
    The terminal creates a separate MarketDataStore instance under
    TERMINAL_MARKET_DATA_KEY so terminal pages do not cross-
    contaminate the (app) dashboard's store.
-->
<script lang="ts">
	import type { Snippet } from "svelte";
	import { getContext, setContext } from "svelte";
	import {
		createMarketDataStore,
		type MarketDataStore,
	} from "$lib/stores/market-data.svelte";
	import { TERMINAL_MARKET_DATA_KEY } from "$lib/components/portfolio/live/workbench-state";
	import TerminalShell from "$lib/components/terminal/shell/TerminalShell.svelte";

	let { children }: { children: Snippet } = $props();

	// Consume the Clerk token provider set by the root layout.
	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// Terminal-scoped MarketDataStore — separate WS connection from
	// the (app) dashboard's store.
	const marketStore = createMarketDataStore({ getToken });
	setContext<MarketDataStore>(TERMINAL_MARKET_DATA_KEY, marketStore);
</script>

<TerminalShell>
	{@render children()}
</TerminalShell>
