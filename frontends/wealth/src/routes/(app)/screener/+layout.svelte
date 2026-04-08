<!--
  Screener Layout — Persistent pill navigation across all screener sub-routes.
  Back chevron < | Screening | Analytics | DD Reviews          [Run Review]
  Figma node 5-2124.
-->
<script lang="ts">
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import { getContext } from "svelte";
  import { ChevronLeft, Sparkles, Loader2, FileCheck } from "lucide-svelte";
  import { createClientApiClient } from "$lib/api/client";
  import type { Snippet } from "svelte";

  let { children }: { children: Snippet } = $props();

  const getToken = getContext<() => Promise<string>>("netz:getToken");
  const api = createClientApiClient(getToken);

  const TABS = [
    // DD Reviews pill removed in Phase 7 of the Wealth Library
    // sprint (spec §2.4) — the entire reading workbench moved into
    // /library. Screener keeps its two clean pillars: Screening and
    // Analytics. Legacy /screener/dd-reports/* URLs still resolve via
    // 308 redirects in the route loaders.
    { key: "screening", href: "/screener",           label: "Screening" },
    { key: "analytics", href: "/screener/analytics",  label: "Analytics" },
  ] as const;

  let activeTab = $derived.by(() => {
    const path = $page.url.pathname;
    if (path.startsWith("/screener/analytics")) return "analytics";
    return "screening";
  });

  /** Show back chevron in detail sub-routes (NOT fund pages — they have their own back) */
  let showBack = $derived.by(() => {
    const path = $page.url.pathname;
    if (path.startsWith("/screener/fund/")) return false;
    return path.startsWith("/screener/runs/");
  });

  /** Are we on any fund detail page (fact sheet OR risk analysis sub-tab)? */
  let fundPageId = $derived.by(() => {
    const match = $page.url.pathname.match(/^\/screener\/fund\/([^/]+)(?:\/.*)?$/);
    return match ? match[1] : null;
  });

  function goBack() {
    // Navigate back to the previous context (L2 fund list, DD list, etc.)
    history.back();
  }

  // ── DD Report action (only active on fund pages) ──
  let ddGenerating = $state(false);

  async function runDDReport() {
    if (ddGenerating || !fundPageId) return;
    ddGenerating = true;
    try {
      const result = await api.post<{ id: string; instrument_id: string }>("/dd-reports/generate", {
        instrument_external_id: fundPageId,
      });
      // Send users straight into the Library — the legacy URL would
      // still work via the Phase 7 308 redirect, but the canonical
      // landing avoids the extra hop.
      goto(`/library?id=${result.id}`);
    } catch {
      ddGenerating = false;
    }
  }
</script>

<div class="scr-layout">
  <!-- ── Pill Nav Bar ── -->
  <nav class="scr-nav">
    <div class="scr-nav-left">
      {#if showBack}
        <button class="scr-back" onclick={goBack} aria-label="Back">
          <ChevronLeft size={20} />
        </button>
      {/if}

      <div class="scr-pills">
        {#each TABS as tab (tab.key)}
          <a
            href={tab.href}
            class="scr-pill"
            class:scr-pill--active={activeTab === tab.key}
            data-sveltekit-noscroll
          >
            {tab.label}
          </a>
        {/each}
      </div>
    </div>

    {#if fundPageId}
      <button
        class="scr-pill scr-pill--action"
        onclick={runDDReport}
        disabled={ddGenerating}
      >
        {#if ddGenerating}
          <Loader2 size={18} class="animate-spin" />
          Generating...
        {:else}
          <Sparkles size={18} />
          Run Review
        {/if}
      </button>
    {/if}
  </nav>

  <!-- ── Child Content ── -->
  <div class="scr-slot">
    {@render children()}
  </div>
</div>

<style>
  .scr-layout {
    /*
     * Fixed height = viewport minus topbar(88px) minus black padding(68px).
     * This creates a contained flex column so child tables scroll internally
     * instead of pushing the outer main scrollbar.
     */
    height: calc(100vh - 88px - 68px);
    display: flex;
    flex-direction: column;
    padding: 24px;
    gap: 34px;
    overflow: hidden;
  }

  /* ── Nav Bar ── */
  .scr-nav {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
  }

  .scr-nav-left {
    display: flex;
    align-items: center;
    gap: 0;
  }

  /* ── Back Chevron — same height as pills ── */
  .scr-back {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 48px;
    height: 48px;
    border-radius: 36px;
    border: 1px solid #fff;
    background: #000;
    color: #fff;
    cursor: pointer;
    transition: background 120ms ease;
    flex-shrink: 0;
    margin-right: 8px;
  }

  .scr-back:hover {
    background: #1a1b20;
  }

  /* ── Pills ── */
  .scr-pills {
    display: flex;
    gap: 0;
  }

  .scr-pill {
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

  .scr-pill:hover {
    background: #1a1b20;
  }

  .scr-pill--active {
    background: #0177fb;
    border-color: transparent;
  }

  .scr-pill--active:hover {
    background: #0166d9;
  }

  /* ── Run Review action pill ── */
  .scr-pill--action {
    background: #0177fb;
    border-color: transparent;
    font-weight: 600;
  }

  .scr-pill--action:hover:not(:disabled) {
    background: #0166d9;
  }

  .scr-pill--action:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  /* ── Slot — overflow hidden; each page manages its own scroll ── */
  .scr-slot {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }
</style>
