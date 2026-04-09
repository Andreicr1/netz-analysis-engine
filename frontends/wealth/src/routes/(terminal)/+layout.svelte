<!--
  (terminal) — full-screen Bloomberg-style layout group.

  Phase 9 "Terminal Breakout" mandate. The Live Workbench, and any
  future execution surfaces that must escape the SaaS chrome, live
  under this route group. There is NO topbar, NO left sidebar, NO
  PortfolioSubNav ribbon, NO welcome banner, NO AiAgentDrawer, NO
  GlobalSearch, NO theme wrapper. The page fills 100vw × 100vh and
  claims the viewport for itself.

  Inheritance chain:
    src/routes/+layout.server.ts   — hydrates ``actor`` + ``token``
    src/routes/+layout.svelte      — root layout (theme, fonts)
    src/routes/(terminal)/+layout.svelte — THIS FILE
    src/routes/(terminal)/portfolio/live/+page.* — the workbench

  The root +layout.svelte is kept in the chain so Clerk context,
  fonts, theme tokens, and the base CSS reset still apply. Only the
  (app)/+layout.svelte with its sidebar/topbar/drawer stack is
  skipped — that is the entire point of the breakout.

  Scroll discipline: body-level scroll is killed via ``overflow:
  hidden`` on the root div. Anything that needs to scroll must do
  so inside its own panel (see LiveWorkbenchShell allocations
  footer for the pattern).
-->
<script lang="ts">
	import type { Snippet } from "svelte";

	let { children }: { children: Snippet } = $props();
</script>

<div class="terminal-root">
	{@render children()}
</div>

<style>
	.terminal-root {
		/* Full-viewport lock — zero chrome inheritance. */
		position: fixed;
		inset: 0;
		width: 100vw;
		height: 100vh;
		overflow: hidden;
		background: #0a0e17;
		color: #ffffff;
		font-family: "Urbanist", system-ui, sans-serif;
		/* Isolate paint so any transform / filter inside the terminal
		   does not leak into the root stacking context. */
		isolation: isolate;
		z-index: 1;
	}

	/* Kill body scroll so nothing can push past the terminal box. */
	:global(body:has(.terminal-root)) {
		overflow: hidden;
	}
</style>
