/**
 * Terminal workbench state — Phase 2 Terminal Grid Shell.
 *
 * Stripped to portfolio selection only. The old WorkbenchTool /
 * tab-based state machine was removed along with WorkbenchToolRibbon
 * and LivePortfolioSidebar. The terminal grid is a fixed 4-zone
 * layout with no tab switching.
 *
 * Source-of-truth discipline (DL15 — Zero localStorage):
 *   The parent +page.svelte reads the selected portfolio from
 *   ``page.url.searchParams.get("portfolio")`` and writes it back
 *   via ``goto({replaceState, noScroll, keepFocus})``. This module
 *   exports pure types — there is NO in-module $state, no store.
 */

/** Context key for the terminal-scoped MarketDataStore. */
export const TERMINAL_MARKET_DATA_KEY = "netz:terminal:marketDataStore";
