/**
 * @investintell/ii-terminal-core — barrel
 *
 * Top-level exports for the most frequently-imported entry points.
 * Deep imports (live/, builder/, allocation/, screener-terminal/,
 * macro/, dd/, focus-mode/) remain available via subpath exports:
 *   @investintell/ii-terminal-core/components/terminal/live/...
 *   @investintell/ii-terminal-core/stores/market-data.svelte
 *   @investintell/ii-terminal-core/types/portfolio-build
 *   @investintell/ii-terminal-core/utils/sse-reader
 *   @investintell/ii-terminal-core/constants/blocks
 *   @investintell/ii-terminal-core/api/client
 */

// Shell
export { default as TerminalShell } from "./components/terminal/shell/TerminalShell.svelte";
export { default as TerminalTopNav } from "./components/terminal/shell/TerminalTopNav.svelte";
export { default as TerminalStatusBar } from "./components/terminal/shell/TerminalStatusBar.svelte";
export { default as TerminalBreadcrumb } from "./components/terminal/shell/TerminalBreadcrumb.svelte";
export { default as TerminalContextRail } from "./components/terminal/shell/TerminalContextRail.svelte";
export { default as TerminalTweaksPanel } from "./components/terminal/shell/TerminalTweaksPanel.svelte";
export { default as LayoutCage } from "./components/terminal/shell/LayoutCage.svelte";
export { default as AlertTicker } from "./components/terminal/shell/AlertTicker.svelte";
export { default as LiveMarquee } from "./components/terminal/shell/LiveMarquee.svelte";
export { default as MarketFeedList } from "./components/terminal/shell/MarketFeedList.svelte";
export { default as CommandPalette } from "./components/terminal/shell/CommandPalette.svelte";

// Terminal primitives
export * from "./components/terminal/primitives";

// Focus mode
export { default as FundFocusMode } from "./components/terminal/focus-mode/fund/FundFocusMode.svelte";

// Stores
export {
	createMarketDataStore,
	type MarketDataStore,
	type MarketDataStoreConfig,
	type PriceTick,
	type HoldingSummary,
	type DashboardSnapshot,
	type WsStatus,
} from "./stores/market-data.svelte";
export {
	createTerminalTweaks,
	TERMINAL_TWEAKS_KEY,
	type TerminalTweaks,
} from "./stores/terminal-tweaks.svelte";
export {
	palette,
	PaletteState,
	openPalette,
	closePalette,
	togglePalette,
	setPaletteQuery,
	setPaletteSelectedIndex,
} from "./stores/palette.svelte";

// State
export {
	workspace,
	PortfolioWorkspaceState,
	type CascadePhase,
	type ConstructionStressResult,
	type ConstructionValidationResult,
	type ConstructionNarrativeContent,
	type StressResultView,
	type UniverseFund,
	type WorkspaceError,
	type FactorContribution,
	type FactorAnalysisResponse,
} from "./state/portfolio-workspace.svelte";
export { pinnedRegime, type PinnedRegime } from "./state/pinned-regime.svelte";

// API
export {
	createClientApiClient,
	createServerApiClient,
	setAuthRedirectHandler,
	setConflictHandler,
} from "./api/client";
