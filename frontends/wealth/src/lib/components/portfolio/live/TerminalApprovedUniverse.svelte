<!--
  TerminalApprovedUniverse — EDIT mode left panel (replaces NewsFeed).

  Ultra-dense Tiingo-style table listing approved universe instruments.
  Each row has a [+] button to inject into draftHoldings.
  Already-added instruments show a checkmark instead of [+].

  Mock data for now — will be wired to GET /universe API.
-->
<script lang="ts">
	import type { DraftHolding } from "./LiveWorkbenchShell.svelte";

	interface Props {
		draftHoldings: DraftHolding[];
		onAdd: (instrument: { instrument_id: string; fund_name: string; block_id: string }) => void;
	}

	let { draftHoldings, onAdd }: Props = $props();

	interface UniverseInstrument {
		instrument_id: string;
		fund_name: string;
		ticker: string;
		block_id: string;
	}

	// Mock approved universe — will be fetched from API
	const MOCK_UNIVERSE: UniverseInstrument[] = [
		{ instrument_id: "u-001", fund_name: "Vanguard Total Bond Market ETF", ticker: "BND", block_id: "fixed_income" },
		{ instrument_id: "u-002", fund_name: "iShares Core US Aggregate Bond", ticker: "AGG", block_id: "fixed_income" },
		{ instrument_id: "u-003", fund_name: "PIMCO Income Fund", ticker: "PONAX", block_id: "fixed_income" },
		{ instrument_id: "u-004", fund_name: "Vanguard Total Stock Market ETF", ticker: "VTI", block_id: "equity" },
		{ instrument_id: "u-005", fund_name: "SPDR S&P 500 ETF", ticker: "SPY", block_id: "equity" },
		{ instrument_id: "u-006", fund_name: "iShares MSCI EAFE ETF", ticker: "EFA", block_id: "equity_intl" },
		{ instrument_id: "u-007", fund_name: "Vanguard FTSE Emerging Markets", ticker: "VWO", block_id: "equity_em" },
		{ instrument_id: "u-008", fund_name: "iShares Gold Trust", ticker: "IAU", block_id: "commodities" },
		{ instrument_id: "u-009", fund_name: "Vanguard Real Estate ETF", ticker: "VNQ", block_id: "real_estate" },
		{ instrument_id: "u-010", fund_name: "SPDR Bloomberg High Yield Bond", ticker: "JNK", block_id: "high_yield" },
		{ instrument_id: "u-011", fund_name: "iShares TIPS Bond ETF", ticker: "TIP", block_id: "inflation_linked" },
		{ instrument_id: "u-012", fund_name: "Invesco QQQ Trust", ticker: "QQQ", block_id: "equity" },
		{ instrument_id: "u-013", fund_name: "Schwab US Dividend Equity ETF", ticker: "SCHD", block_id: "equity" },
		{ instrument_id: "u-014", fund_name: "iShares 20+ Year Treasury Bond", ticker: "TLT", block_id: "fixed_income" },
		{ instrument_id: "u-015", fund_name: "Vanguard Short-Term Bond ETF", ticker: "BSV", block_id: "fixed_income" },
	];

	let searchQuery = $state("");

	const draftIds = $derived(new Set(draftHoldings.map((h) => h.instrument_id)));

	const filtered = $derived.by(() => {
		if (!searchQuery.trim()) return MOCK_UNIVERSE;
		const q = searchQuery.toLowerCase();
		return MOCK_UNIVERSE.filter(
			(i) =>
				i.fund_name.toLowerCase().includes(q) ||
				i.ticker.toLowerCase().includes(q) ||
				i.block_id.toLowerCase().includes(q),
		);
	});
</script>

<div class="au-root">
	<div class="au-header">
		<span class="au-title">APPROVED UNIVERSE</span>
		<span class="au-count">{MOCK_UNIVERSE.length}</span>
	</div>

	<div class="au-search">
		<input
			type="text"
			class="au-search-input"
			placeholder="Search ticker, name..."
			bind:value={searchQuery}
		/>
	</div>

	<div class="au-list">
		{#each filtered as inst}
			{@const inDraft = draftIds.has(inst.instrument_id)}
			<div class="au-row" class:au-row--added={inDraft}>
				<div class="au-row-left">
					<span class="au-ticker">{inst.ticker}</span>
					<span class="au-name" title={inst.fund_name}>{inst.fund_name}</span>
				</div>
				<button
					type="button"
					class="au-add-btn"
					class:au-add-btn--done={inDraft}
					disabled={inDraft}
					onclick={() => onAdd({ instrument_id: inst.instrument_id, fund_name: inst.fund_name, block_id: inst.block_id })}
					title={inDraft ? "Already added" : "Add to draft"}
					aria-label={inDraft ? `${inst.ticker} already added` : `Add ${inst.ticker}`}
				>
					{inDraft ? "\u2713" : "+"}
				</button>
			</div>
		{/each}
		{#if filtered.length === 0}
			<div class="au-empty">No matching instruments</div>
		{/if}
	</div>
</div>

<style>
	.au-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.au-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
		height: 30px;
		padding: 0 10px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
	}
	.au-title {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: #2d7ef7;
	}
	.au-count {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		font-weight: 700;
		color: #5a6577;
	}

	/* ── Search bar ─────────────────────────────────────────── */
	.au-search {
		flex-shrink: 0;
		padding: 4px 6px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.04);
	}
	.au-search-input {
		width: 100%;
		height: 26px;
		padding: 0 8px;
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		color: #c8d0dc;
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid rgba(255, 255, 255, 0.08);
		outline: none;
		transition: border-color 80ms;
	}
	.au-search-input::placeholder {
		color: #3d4654;
	}
	.au-search-input:focus {
		border-color: rgba(45, 126, 247, 0.4);
	}

	/* ── Scrollable list ────────────────────────────────────── */
	.au-list {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.au-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 4px;
		padding: 4px 8px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.03);
		cursor: default;
		transition: background 60ms;
	}
	.au-row:hover {
		background: rgba(255, 255, 255, 0.03);
	}
	.au-row--added {
		opacity: 0.5;
	}

	.au-row-left {
		display: flex;
		flex-direction: column;
		gap: 1px;
		min-width: 0;
		flex: 1;
	}

	.au-ticker {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		font-weight: 700;
		color: #c8d0dc;
		letter-spacing: 0.04em;
	}
	.au-name {
		font-size: 10px;
		font-weight: 400;
		color: #5a6577;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* ── Add button ─────────────────────────────────────────── */
	.au-add-btn {
		appearance: none;
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		padding: 0;
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 14px;
		font-weight: 700;
		color: #2d7ef7;
		background: rgba(45, 126, 247, 0.08);
		border: 1px solid rgba(45, 126, 247, 0.20);
		cursor: pointer;
		transition: background 60ms, color 60ms;
	}
	.au-add-btn:hover:not(:disabled) {
		background: rgba(45, 126, 247, 0.16);
		color: #5ba0ff;
	}
	.au-add-btn--done {
		color: #22c55e;
		background: rgba(34, 197, 94, 0.08);
		border-color: rgba(34, 197, 94, 0.20);
		cursor: default;
		font-size: 11px;
	}

	.au-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 80px;
		font-size: 11px;
		color: #3d4654;
	}
</style>
