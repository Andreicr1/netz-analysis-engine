<!--
  Portfolio Layout — Phase 5 Task 5.5 of the portfolio-enterprise-workbench
  plan. Replaces the legacy 4-pill nav (Builder | Model | Analytics &
  Risk | Advanced) with the canonical DL1 3-phase ribbon (Builder |
  Analytics | Live).

  The legacy /portfolio/model and /portfolio/advanced routes still
  exist as files; Phase 10 Task 10.3 will add hooks.server.ts redirects
  and delete the route directories. Removing them from the visible
  navigation is the Phase 5 contribution to the legacy cleanup.

  Per DL1 — sub-nav is sticky under TopNav and visible on every
  /portfolio/* route. Phase 6 will fill ``subjectsUnderAnalysis`` from
  the new BottomTabDock; Phase 7 will fill ``liveAlertsCount`` from
  the unified portfolio_alerts feed; Phase 9 will fill
  ``draftsInProgress`` from a derived workspace count.
-->
<script lang="ts">
  import type { Snippet } from "svelte";
  import PortfolioSubNav from "$lib/components/portfolio/PortfolioSubNav.svelte";
  import { workspace } from "$lib/state/portfolio-workspace.svelte";

  let { children }: { children: Snippet } = $props();

  // Phase 7 — feed the "Live" pill badge from the unified alerts
  // inbox. The GlobalAlertInbox in (app)/+layout.svelte owns the
  // polling lifecycle; this layout is a pure reader. Drift alerts
  // are instrument-keyed and not portfolio-attributable without
  // the holdings join (deferred to a follow-up sprint), so the
  // badge reflects only the portfolio-sourced count.
  const liveAlertsCount = $derived(
    workspace.alertsInbox?.by_source?.portfolio ?? 0,
  );
</script>

<div class="pw-layout">
  <!-- ── Phase 5 sub-nav ribbon (DL1) ── -->
  <header class="pw-nav">
    <PortfolioSubNav {liveAlertsCount} />
  </header>

  <!-- ── Child Content ── -->
  <div class="pw-slot">
    {@render children()}
  </div>
</div>

<style>
  .pw-layout {
    /* Topbar = 72px (shell), pills row = ~68px.
     * Full-bleed — no horizontal padding so the Flexible Columns
     * Layout inside the Builder page fills every pixel of the
     * workspace canvas. Top padding keeps the pills breathing. */
    height: calc(100vh - 72px);
    display: flex;
    flex-direction: column;
    padding: 16px 16px 0 16px;
    gap: 16px;
    overflow: hidden;
    background: #0e0f13;
  }

  .pw-nav {
    display: flex;
    align-items: center;
    flex-shrink: 0;
  }

  /* ── Slot — overflow hidden; each page manages its own scroll ── */
  .pw-slot {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }
</style>
