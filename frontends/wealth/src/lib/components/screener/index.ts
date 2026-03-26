// ── Unified Screener components ──
export { default as CatalogFilterSidebar } from "./CatalogFilterSidebar.svelte";
export { default as CatalogTable } from "./CatalogTable.svelte";
export { default as CatalogDetailPanel } from "./CatalogDetailPanel.svelte";

// ── Global Securities (equities — no RLS) ──
export { default as SecuritiesTable } from "./SecuritiesTable.svelte";
export { default as SecuritiesFilterSidebar } from "./SecuritiesFilterSidebar.svelte";

// ── Instrument (tenant universe) ──
export { default as InstrumentFilterSidebar } from "./InstrumentFilterSidebar.svelte";
export { default as ManagerFilterSidebar } from "./ManagerFilterSidebar.svelte";
export { default as ScreenerFilters } from "./ScreenerFilters.svelte";
export { default as InstrumentTable } from "./InstrumentTable.svelte";
export { default as InstrumentDetailPanel } from "./InstrumentDetailPanel.svelte";
export { default as FundDetailPanel } from "./FundDetailPanel.svelte";

// ── Manager hierarchy ──
export { default as ManagerHierarchyTable } from "./ManagerHierarchyTable.svelte";
export { default as ManagerDetailPanel } from "./ManagerDetailPanel.svelte";
export { default as PeerComparisonView } from "./PeerComparisonView.svelte";

// ── SEC analysis (moved from us-fund-analysis) ──
export { default as SecManagerTable } from "./SecManagerTable.svelte";
export { default as SecHoldingsTable } from "./SecHoldingsTable.svelte";
export { default as SecStyleDriftChart } from "./SecStyleDriftChart.svelte";
export { default as SecReverseLookup } from "./SecReverseLookup.svelte";
export { default as SecPeerCompare } from "./SecPeerCompare.svelte";

// ── Tabs (kept for backward compat) ──
export { default as DriftTab } from "./DriftTab.svelte";
export { default as HoldingsTab } from "./HoldingsTab.svelte";
export { default as DocsTab } from "./DocsTab.svelte";
