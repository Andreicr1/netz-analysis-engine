<!--
  Portfolio Layout — Persistent pill navigation across portfolio sub-routes.
  Builder | Model | Analytics & Risk
  Mirrors Screener layout architecture (same pill sizes, spacing, active state).
-->
<script lang="ts">
  import { page } from "$app/stores";
  import type { Snippet } from "svelte";

  let { children }: { children: Snippet } = $props();

  const TABS = [
    { key: "builder",   href: "/portfolio",           label: "Builder" },
    { key: "model",     href: "/portfolio/model",      label: "Model" },
    { key: "analytics", href: "/portfolio/analytics",  label: "Analytics & Risk" },
  ] as const;

  let activeTab = $derived.by(() => {
    const path = $page.url.pathname;
    if (path.startsWith("/portfolio/analytics")) return "analytics";
    if (path.startsWith("/portfolio/model")) return "model";
    return "builder";
  });
</script>

<div class="pw-layout">
  <!-- ── Pill Nav Bar ── -->
  <nav class="pw-nav">
    <div class="pw-pills">
      {#each TABS as tab (tab.key)}
        <a
          href={tab.href}
          class="pw-pill"
          class:pw-pill--active={activeTab === tab.key}
          data-sveltekit-noscroll
        >
          {tab.label}
        </a>
      {/each}
    </div>
  </nav>

  <!-- ── Child Content ── -->
  <div class="pw-slot">
    {@render children()}
  </div>
</div>

<style>
  .pw-layout {
    height: calc(100vh - 88px - 68px);
    display: flex;
    flex-direction: column;
    padding: 24px;
    gap: 34px;
    overflow: hidden;
  }

  /* ── Nav Bar ── */
  .pw-nav {
    display: flex;
    align-items: center;
    flex-shrink: 0;
  }

  /* ── Pills — exact Screener match ── */
  .pw-pills {
    display: flex;
    gap: 0;
  }

  .pw-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 14px 24px;
    border: 1px solid #fff;
    border-radius: 36px;
    background: #000;
    color: #fff;
    font-size: 17px;
    font-weight: 400;
    font-family: "Urbanist", sans-serif;
    cursor: pointer;
    white-space: nowrap;
    transition: background 120ms ease;
    text-decoration: none;
  }

  .pw-pill:hover {
    background: #1a1b20;
  }

  .pw-pill--active {
    background: #0177fb;
    border-color: transparent;
  }

  .pw-pill--active:hover {
    background: #0166d9;
  }

  /* ── Slot — overflow hidden; each page manages its own scroll ── */
  .pw-slot {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }
</style>
