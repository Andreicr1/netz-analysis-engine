<!--
  TerminalScreenerShell — 3-column high-density screener grid.

  Grid topology:
    ┌──────────┬──────────────────────┬─────────────┐
    │          │                      │             │
    │ FILTERS  │      DATA GRID       │ QUICK STATS │
    │ (280px)  │       (1fr)          │   (320px)   │
    │          │                      │             │
    └──────────┴──────────────────────┴─────────────┘

  All zones enforce min-width:0, min-height:0, overflow:hidden
  to protect the parent layout from blowout.
-->
<script lang="ts">
	import TerminalScreenerFilters from "./TerminalScreenerFilters.svelte";
	import TerminalDataGrid, { type MockAsset } from "./TerminalDataGrid.svelte";
	import TerminalScreenerQuickStats from "./TerminalScreenerQuickStats.svelte";

	// ── Filter state ──────────────────────────────────
	let filters = $state({
		sectors: new Set<string>(),
		assetClasses: new Set<string>(),
		returnMin: -50,
		returnMax: 100,
		volMin: 0,
		volMax: 60,
		drawdownMin: -80,
		drawdownMax: 0,
	});

	// ── Selection state ───────────────────────────────
	let selectedId = $state<string | null>(null);

	// ── Mock data (30 instruments) ────────────────────
	const MOCK_ASSETS: MockAsset[] = [
		{ id: "1",  ticker: "VFIAX",   name: "Vanguard 500 Index Fund",            assetClass: "Equity",       sector: "Technology",     ret1y: 26.42, ret3y: 12.18,  volatility: 14.8,  sharpe: 1.42,  maxDrawdown: -9.2,   beta: 1.00, alpha: 0.12,  aum: 432e9, expenseRatio: 0.04, dtwDriftScore: 0.08 },
		{ id: "2",  ticker: "FXAIX",   name: "Fidelity 500 Index Fund",            assetClass: "Equity",       sector: "Technology",     ret1y: 26.38, ret3y: 12.15,  volatility: 14.7,  sharpe: 1.43,  maxDrawdown: -9.1,   beta: 1.00, alpha: 0.10,  aum: 510e9, expenseRatio: 0.02, dtwDriftScore: 0.05 },
		{ id: "3",  ticker: "PIMIX",   name: "PIMCO Income Fund",                  assetClass: "Fixed Income", sector: "Financials",     ret1y: 8.74,  ret3y: 3.92,   volatility: 5.2,   sharpe: 1.12,  maxDrawdown: -4.8,   beta: 0.15, alpha: 2.31,  aum: 148e9, expenseRatio: 0.75, dtwDriftScore: 0.52 },
		{ id: "4",  ticker: "TRBCX",   name: "T. Rowe Price Blue Chip Growth",     assetClass: "Equity",       sector: "Technology",     ret1y: 32.14, ret3y: 8.42,   volatility: 19.6,  sharpe: 1.28,  maxDrawdown: -18.3,  beta: 1.12, alpha: 3.50,  aum: 52e9,  expenseRatio: 0.69, dtwDriftScore: 0.93 },
		{ id: "5",  ticker: "DODFX",   name: "Dodge & Cox International Stock",    assetClass: "Equity",       sector: "Financials",     ret1y: 11.83, ret3y: 6.07,   volatility: 16.1,  sharpe: 0.82,  maxDrawdown: -14.5,  beta: 0.88, alpha: 1.24,  aum: 62e9,  expenseRatio: 0.62, dtwDriftScore: 0.34 },
		{ id: "6",  ticker: "VBTLX",   name: "Vanguard Total Bond Market Index",   assetClass: "Fixed Income", sector: "Financials",     ret1y: 1.23,  ret3y: -2.14,  volatility: 6.8,   sharpe: 0.18,  maxDrawdown: -13.1,  beta: 0.02, alpha: -0.32, aum: 316e9, expenseRatio: 0.05, dtwDriftScore: 0.12 },
		{ id: "7",  ticker: "VWELX",   name: "Vanguard Wellington Fund",            assetClass: "Multi-Asset",  sector: "Financials",     ret1y: 14.52, ret3y: 5.83,   volatility: 10.4,  sharpe: 1.06,  maxDrawdown: -10.2,  beta: 0.62, alpha: 1.88,  aum: 110e9, expenseRatio: 0.25, dtwDriftScore: 0.18 },
		{ id: "8",  ticker: "PRWCX",   name: "T. Rowe Price Capital Appreciation", assetClass: "Multi-Asset",  sector: "Technology",     ret1y: 18.96, ret3y: 7.14,   volatility: 11.8,  sharpe: 1.22,  maxDrawdown: -11.4,  beta: 0.68, alpha: 3.12,  aum: 48e9,  expenseRatio: 0.70, dtwDriftScore: 0.67 },
		{ id: "9",  ticker: "OAKBX",   name: "Oakmark International Fund",         assetClass: "Equity",       sector: "Industrials",    ret1y: 9.47,  ret3y: 4.28,   volatility: 17.3,  sharpe: 0.68,  maxDrawdown: -16.8,  beta: 0.92, alpha: 0.88,  aum: 14e9,  expenseRatio: 0.93, dtwDriftScore: 0.91 },
		{ id: "10", ticker: "FCNTX",   name: "Fidelity Contrafund",                assetClass: "Equity",       sector: "Technology",     ret1y: 29.31, ret3y: 10.82,  volatility: 16.4,  sharpe: 1.38,  maxDrawdown: -12.7,  beta: 1.05, alpha: 2.94,  aum: 130e9, expenseRatio: 0.39, dtwDriftScore: 0.22 },
		{ id: "11", ticker: "MWTRX",   name: "Metropolitan West Total Return Bd",  assetClass: "Fixed Income", sector: "Financials",     ret1y: 2.18,  ret3y: -1.42,  volatility: 5.9,   sharpe: 0.24,  maxDrawdown: -11.4,  beta: 0.04, alpha: 0.18,  aum: 86e9,  expenseRatio: 0.38, dtwDriftScore: 0.15 },
		{ id: "12", ticker: "VTSAX",   name: "Vanguard Total Stock Market Index",  assetClass: "Equity",       sector: "Technology",     ret1y: 25.18, ret3y: 10.94,  volatility: 15.2,  sharpe: 1.32,  maxDrawdown: -10.8,  beta: 1.02, alpha: -0.04, aum: 380e9, expenseRatio: 0.04, dtwDriftScore: 0.07 },
		{ id: "13", ticker: "AGTHX",   name: "American Funds Growth Fund",         assetClass: "Equity",       sector: "Healthcare",     ret1y: 22.64, ret3y: 7.53,   volatility: 17.8,  sharpe: 1.04,  maxDrawdown: -15.6,  beta: 1.08, alpha: 1.42,  aum: 240e9, expenseRatio: 0.62, dtwDriftScore: 0.44 },
		{ id: "14", ticker: "VTMGX",   name: "Vanguard Developed Markets Index",   assetClass: "Equity",       sector: "Industrials",    ret1y: 10.42, ret3y: 5.18,   volatility: 14.6,  sharpe: 0.78,  maxDrawdown: -12.3,  beta: 0.84, alpha: 0.36,  aum: 165e9, expenseRatio: 0.07, dtwDriftScore: 0.11 },
		{ id: "15", ticker: "PTTRX",   name: "PIMCO Total Return Fund",            assetClass: "Fixed Income", sector: "Financials",     ret1y: 3.42,  ret3y: -0.94,  volatility: 5.4,   sharpe: 0.38,  maxDrawdown: -9.8,   beta: 0.06, alpha: 0.42,  aum: 64e9,  expenseRatio: 0.46, dtwDriftScore: 0.28 },
		{ id: "16", ticker: "DFIVX",   name: "DFA International Value Fund",       assetClass: "Equity",       sector: "Energy",         ret1y: 13.28, ret3y: 8.64,   volatility: 15.8,  sharpe: 0.92,  maxDrawdown: -13.6,  beta: 0.86, alpha: 2.14,  aum: 18e9,  expenseRatio: 0.27, dtwDriftScore: 0.38 },
		{ id: "17", ticker: "RERGX",   name: "American Funds EuroPacific Growth",  assetClass: "Equity",       sector: "Communication",  ret1y: 7.84,  ret3y: 2.36,   volatility: 16.2,  sharpe: 0.56,  maxDrawdown: -17.4,  beta: 0.90, alpha: -0.28, aum: 120e9, expenseRatio: 0.46, dtwDriftScore: 0.96 },
		{ id: "18", ticker: "HAINX",   name: "Harbor International Fund",          assetClass: "Equity",       sector: "Healthcare",     ret1y: 8.92,  ret3y: 3.78,   volatility: 15.4,  sharpe: 0.64,  maxDrawdown: -15.2,  beta: 0.82, alpha: 0.68,  aum: 22e9,  expenseRatio: 0.72, dtwDriftScore: 0.55 },
		{ id: "19", ticker: "VGSLX",   name: "Vanguard Real Estate Index",         assetClass: "Alternative",  sector: "Real Estate",    ret1y: 4.83,  ret3y: 1.24,   volatility: 18.6,  sharpe: 0.34,  maxDrawdown: -22.8,  beta: 0.72, alpha: -1.14, aum: 72e9,  expenseRatio: 0.12, dtwDriftScore: 0.72 },
		{ id: "20", ticker: "DFALX",   name: "DFA US Large Cap Value Fund",        assetClass: "Equity",       sector: "Financials",     ret1y: 15.62, ret3y: 9.84,   volatility: 14.2,  sharpe: 1.04,  maxDrawdown: -11.2,  beta: 0.94, alpha: 1.62,  aum: 28e9,  expenseRatio: 0.18, dtwDriftScore: 0.19 },
		{ id: "21", ticker: "TRCVX",   name: "T. Rowe Price Mid-Cap Value",        assetClass: "Equity",       sector: "Industrials",    ret1y: 12.84, ret3y: 7.42,   volatility: 16.8,  sharpe: 0.88,  maxDrawdown: -14.8,  beta: 0.96, alpha: 1.34,  aum: 8e9,   expenseRatio: 0.76, dtwDriftScore: 0.41 },
		{ id: "22", ticker: "VMNVX",   name: "Vanguard Global Minimum Volatility", assetClass: "Equity",       sector: "Utilities",      ret1y: 9.14,  ret3y: 5.62,   volatility: 10.2,  sharpe: 0.92,  maxDrawdown: -8.4,   beta: 0.64, alpha: 0.82,  aum: 6e9,   expenseRatio: 0.17, dtwDriftScore: 0.14 },
		{ id: "23", ticker: "FSMDX",   name: "Fidelity Mid Cap Index Fund",        assetClass: "Equity",       sector: "Consumer Discretionary", ret1y: 14.26, ret3y: 6.38, volatility: 17.4, sharpe: 0.84, maxDrawdown: -15.4, beta: 1.06, alpha: 0.48, aum: 32e9, expenseRatio: 0.03, dtwDriftScore: 0.09 },
		{ id: "24", ticker: "BCOIX",   name: "BlackRock Commodity Strategy",       assetClass: "Commodity",    sector: "Materials",      ret1y: -3.84, ret3y: 8.92,   volatility: 22.4,  sharpe: 0.12,  maxDrawdown: -28.6,  beta: 0.42, alpha: -2.84, aum: 4e9,   expenseRatio: 0.68, dtwDriftScore: 0.88 },
		{ id: "25", ticker: "GQETX",   name: "GMO Quality Fund",                   assetClass: "Equity",       sector: "Technology",     ret1y: 24.38, ret3y: 11.42,  volatility: 13.8,  sharpe: 1.38,  maxDrawdown: -8.6,   beta: 0.88, alpha: 4.12,  aum: 15e9,  expenseRatio: 0.48, dtwDriftScore: 0.03 },
		{ id: "26", ticker: "VPCCX",   name: "Vanguard PRIMECAP Core Fund",        assetClass: "Equity",       sector: "Healthcare",     ret1y: 19.72, ret3y: 8.94,   volatility: 15.6,  sharpe: 1.08,  maxDrawdown: -12.4,  beta: 0.96, alpha: 2.42,  aum: 42e9,  expenseRatio: 0.38, dtwDriftScore: 0.31 },
		{ id: "27", ticker: "VIPSX",   name: "Vanguard Inflation-Protected Secs",  assetClass: "Fixed Income", sector: "Financials",     ret1y: 0.84,  ret3y: -0.62,  volatility: 6.4,   sharpe: 0.08,  maxDrawdown: -10.6,  beta: 0.08, alpha: -0.14, aum: 38e9,  expenseRatio: 0.10, dtwDriftScore: null },
		{ id: "28", ticker: "VWIGX",   name: "Vanguard International Growth",      assetClass: "Equity",       sector: "Technology",     ret1y: 16.42, ret3y: 2.84,   volatility: 18.2,  sharpe: 0.78,  maxDrawdown: -22.4,  beta: 0.98, alpha: 0.94,  aum: 50e9,  expenseRatio: 0.32, dtwDriftScore: 0.62 },
		{ id: "29", ticker: "FBALX",   name: "Fidelity Balanced Fund",             assetClass: "Multi-Asset",  sector: "Financials",     ret1y: 16.84, ret3y: 6.42,   volatility: 10.8,  sharpe: 1.14,  maxDrawdown: -9.6,   beta: 0.58, alpha: 2.64,  aum: 36e9,  expenseRatio: 0.49, dtwDriftScore: 0.24 },
		{ id: "30", ticker: "VEMMX",   name: "Vanguard Emerging Markets Stock",    assetClass: "Equity",       sector: "Financials",     ret1y: 8.24,  ret3y: 0.82,   volatility: 18.4,  sharpe: 0.48,  maxDrawdown: -20.4,  beta: 0.78, alpha: -0.62, aum: 82e9,  expenseRatio: 0.14, dtwDriftScore: 0.47 },
	];

	// ── Filtered assets ───────────────────────────────
	const filteredAssets = $derived.by(() => {
		return MOCK_ASSETS.filter((a) => {
			if (filters.sectors.size > 0 && !filters.sectors.has(a.sector)) return false;
			if (filters.assetClasses.size > 0 && !filters.assetClasses.has(a.assetClass)) return false;
			if (a.ret1y < filters.returnMin || a.ret1y > filters.returnMax) return false;
			if (a.volatility < filters.volMin || a.volatility > filters.volMax) return false;
			if (a.maxDrawdown < filters.drawdownMin || a.maxDrawdown > filters.drawdownMax) return false;
			return true;
		});
	});

	const selectedAsset = $derived<MockAsset | null>(
		filteredAssets.find((a) => a.id === selectedId) ?? null,
	);

	function handleSelect(asset: MockAsset) {
		selectedId = asset.id;
	}

	function handleFiltersChange(next: typeof filters) {
		filters = next;
		// Clear selection if filtered out
		if (selectedId && !MOCK_ASSETS.some(
			(a) => a.id === selectedId &&
				(next.sectors.size === 0 || next.sectors.has(a.sector)) &&
				(next.assetClasses.size === 0 || next.assetClasses.has(a.assetClass)),
		)) {
			selectedId = null;
		}
	}
</script>

<div class="ts-root">
	<div class="ts-zone ts-filters" aria-label="Screener filters">
		<TerminalScreenerFilters {filters} onFiltersChange={handleFiltersChange} />
	</div>
	<div class="ts-zone ts-datagrid" aria-label="Instrument data grid">
		<TerminalDataGrid assets={filteredAssets} {selectedId} onSelect={handleSelect} />
	</div>
	<div class="ts-zone ts-stats" aria-label="Quick stats">
		<TerminalScreenerQuickStats asset={selectedAsset} />
	</div>
</div>

<style>
	.ts-root {
		display: grid;
		grid-template-areas: "filters datagrid stats";
		grid-template-columns: 280px 1fr 320px;
		grid-template-rows: 100%;
		gap: 2px;
		width: 100%;
		height: 100%;
		overflow: hidden;
		background: #000000;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.ts-zone {
		min-width: 0;
		min-height: 0;
		overflow: hidden;
	}

	.ts-filters { grid-area: filters; }
	.ts-datagrid { grid-area: datagrid; }
	.ts-stats { grid-area: stats; }
</style>
