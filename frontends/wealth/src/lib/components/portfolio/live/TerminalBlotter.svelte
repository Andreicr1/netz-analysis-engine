<!--
  TerminalBlotter — positions table only (grid-area: blotter).

  Sticky header + sticky footer. Drift-coloured rows. Row click
  selects instrument for chart wiring. No tabs — trade log lives
  in its own TerminalTradeLog component (grid-area: tradelog).

  Typography rules:
    - Instrument name: text-align left, Urbanist 11px
    - Numeric columns: text-align right, JetBrains Mono tabular-nums 10px
-->
<script lang="ts">
	import type { InstrumentWeight } from "$lib/types/model-portfolio";
	import type { ActualHolding } from "./TerminalOmsPanel.svelte";
	import type { DraftHolding, OverlapResultRead, CusipExposure } from "./LiveWorkbenchShell.svelte";

	interface Props {
		mode: "LIVE" | "EDIT";
		targetFunds: InstrumentWeight[];
		actualHoldings: ActualHolding[];
		draftHoldings: DraftHolding[];
		selectedInstrumentId: string | null;
		onInstrumentSelect: (instrumentId: string) => void;
		overlapResult?: OverlapResultRead | null;
	}

	let {
		mode,
		targetFunds,
		actualHoldings,
		draftHoldings,
		selectedInstrumentId,
		onInstrumentSelect,
		overlapResult = null,
	}: Props = $props();

	interface PositionRow {
		instrumentId: string;
		fundName: string;
		target: number;
		actual: number;
		drift: number;
		pnl: number;
	}

	const positions = $derived.by<PositionRow[]>(() => {
		if (mode === "EDIT") {
			// In EDIT mode: show draft holdings with actual=0
			return draftHoldings.map((h) => {
				const target = h.targetWeight / 100; // convert % to decimal
				return {
					instrumentId: h.instrument_id,
					fundName: h.fund_name,
					target,
					actual: 0,
					drift: -target, // needs to be bought
					pnl: 0,
				};
			});
		}
		// LIVE mode: show real positions
		const actualMap = new Map(actualHoldings.map((h) => [h.instrument_id, h.weight]));
		return targetFunds.map((f) => {
			const actual = actualMap.get(f.instrument_id) ?? 0;
			const drift = actual - f.weight;
			const pnl = drift * 10000 + (f.weight - 0.05) * 2000;
			return {
				instrumentId: f.instrument_id,
				fundName: f.fund_name,
				target: f.weight,
				actual,
				drift,
				pnl: Math.round(pnl * 100) / 100,
			};
		});
	});

	const totalTarget = $derived(positions.reduce((s, p) => s + p.target, 0));
	const totalActual = $derived(positions.reduce((s, p) => s + p.actual, 0));
	const totalPnl = $derived(positions.reduce((s, p) => s + p.pnl, 0));

	function driftClass(drift: number): string {
		const abs = Math.abs(drift);
		if (abs >= 0.03) return "bl-drift-red";
		if (abs >= 0.02) return "bl-drift-yellow";
		return "bl-drift-green";
	}

	function fmtPct(n: number): string {
		return (n * 100).toFixed(2) + "%";
	}

	function fmtDrift(n: number): string {
		const pp = n * 100;
		const sign = pp >= 0 ? "+" : "";
		return sign + pp.toFixed(2) + "pp";
	}

	function fmtPnl(n: number): string {
		const sign = n >= 0 ? "+" : "";
		return sign + n.toFixed(0);
	}

	function getBreachForInstrument(instrumentId: string): CusipExposure | null {
		if (mode !== "EDIT" || !overlapResult) return null;
		return overlapResult.breaches.find(b => b.funds_holding.includes(instrumentId)) || null;
	}

	function getBreachTooltip(breach: CusipExposure): string {
		const names = breach.funds_holding.map(id => {
			const h = draftHoldings.find(d => d.instrument_id === id);
			return h ? h.fund_name : id;
		});
		const pct = (breach.total_exposure_pct * 100).toFixed(1);
		const issuer = breach.issuer_name ?? "Unknown";
		return `WARNING: ${pct}% Consolidated Exposure to ${issuer} (${breach.cusip}) across: ${names.join(", ")}.`;
	}
</script>

<div class="bl-root">
	<div class="bl-header">
		<span class="bl-title">{mode === "EDIT" ? "DRAFT POSITIONS" : "POSITIONS"}</span>
		<span class="bl-count">{positions.length}</span>
	</div>

	<div class="bl-body">
		<table class="bl-table">
			<thead>
				<tr>
					<th class="bl-th bl-th--name" scope="col">Instrument</th>
					<th class="bl-th bl-th--num" scope="col">Target</th>
					<th class="bl-th bl-th--num" scope="col">Actual</th>
					<th class="bl-th bl-th--num" scope="col">Drift</th>
					{#if mode === "LIVE"}
						<th class="bl-th bl-th--num" scope="col">P&amp;L</th>
					{/if}
				</tr>
			</thead>
			<tbody>
				{#each positions as pos}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<tr
						class="bl-row"
						class:bl-row--selected={pos.instrumentId === selectedInstrumentId}
						onclick={() => onInstrumentSelect(pos.instrumentId)}
					>
						<th class="bl-td bl-td--name" scope="row" title={pos.fundName}>
							{pos.fundName}
							{#if mode === "EDIT" && overlapResult}
								{@const breach = getBreachForInstrument(pos.instrumentId)}
								{#if breach}
									<span class="bl-overlap-tag" title={getBreachTooltip(breach)}>[ ! OVERLAP ]</span>
								{/if}
							{/if}
						</th>
						<td class="bl-td bl-td--num">{fmtPct(pos.target)}</td>
						<td class="bl-td bl-td--num">{fmtPct(pos.actual)}</td>
						<td class="bl-td bl-td--num {driftClass(pos.drift)}">
							{fmtDrift(pos.drift)}
						</td>
						{#if mode === "LIVE"}
							<td
								class="bl-td bl-td--num"
								class:bl-pnl-up={pos.pnl >= 0}
								class:bl-pnl-down={pos.pnl < 0}
							>{fmtPnl(pos.pnl)}</td>
						{/if}
					</tr>
				{/each}
			</tbody>
			<tfoot>
				<tr>
					<th class="bl-td bl-td--name bl-td--footer" scope="row">Total</th>
					<td class="bl-td bl-td--num bl-td--footer">{fmtPct(totalTarget)}</td>
					<td class="bl-td bl-td--num bl-td--footer">{fmtPct(totalActual)}</td>
					<td class="bl-td bl-td--num bl-td--footer"></td>
					{#if mode === "LIVE"}
						<td
							class="bl-td bl-td--num bl-td--footer"
							class:bl-pnl-up={totalPnl >= 0}
							class:bl-pnl-down={totalPnl < 0}
						>{fmtPnl(totalPnl)}</td>
					{/if}
				</tr>
			</tfoot>
		</table>
	</div>
</div>

<style>
	.bl-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.bl-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
		height: 28px;
		padding: 0 10px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
	}
	.bl-title {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.12em;
		color: #5a6577;
	}
	.bl-count {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		font-weight: 700;
		color: #5a6577;
	}

	.bl-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.bl-table {
		width: 100%;
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
	}

	/* ── Headers: left for name, right for numbers ────────── */
	.bl-th {
		position: sticky;
		top: 0;
		z-index: 2;
		padding: 4px 10px;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: #3d4654;
		background: #0b0f1a;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
		white-space: nowrap;
	}
	.bl-th--name {
		text-align: left;
	}
	.bl-th--num {
		text-align: right;
	}

	/* ── Cells ────────────────────────────────────────────── */
	.bl-td {
		padding: 4px 10px;
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		color: #8896a8;
		border-bottom: 1px solid rgba(255, 255, 255, 0.03);
		white-space: nowrap;
	}
	.bl-td--name {
		text-align: left;
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		font-weight: 500;
		color: #c8d0dc;
		max-width: 260px;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.bl-td--num {
		text-align: right;
	}

	.bl-td--footer {
		font-weight: 700;
		color: #c8d0dc;
		border-top: 1px solid rgba(255, 255, 255, 0.08);
		position: sticky;
		bottom: 0;
		background: #0b0f1a;
	}

	/* ── Row interaction ─────────────────────────────────── */
	.bl-row {
		cursor: pointer;
		transition: background 60ms;
	}
	.bl-row:hover { background: rgba(255, 255, 255, 0.03); }
	.bl-row--selected { background: rgba(45, 126, 247, 0.08); }
	.bl-row--selected:hover { background: rgba(45, 126, 247, 0.12); }

	/* ── Drift colours ───────────────────────────────────── */
	.bl-drift-green { color: #22c55e; }
	.bl-drift-yellow { color: #f59e0b; }
	.bl-drift-red { color: #ef4444; }

	/* ── P&L colours ─────────────────────────────────────── */
	.bl-pnl-up { color: #22c55e; }
	.bl-pnl-down { color: #ef4444; }

	/* ── Overlap Tag ─────────────────────────────────────── */
	.bl-overlap-tag {
		display: inline-block;
		margin-left: 6px;
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 9px;
		font-weight: 700;
		color: #ca8a04;
		vertical-align: middle;
	}
</style>
