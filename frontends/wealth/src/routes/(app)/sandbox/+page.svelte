<script lang="ts">
	import { sandboxBasket } from "$lib/stores/sandbox.svelte";
	import GenericEChart from "$lib/components/charts/GenericEChart.svelte";
	
	// State
	let solver = $state("CLARABEL");
	let maxWeight = $state(10);
	let lookbackWindow = $state(3);
	let loading = $state(false);

	let equityCurveOptions = $state<any>(null);
	let weightsOptions = $state<any>(null);
	let kpis = $state<{ label: string; value: string }[]>([]);

	interface AttributionRow {
		block: string;
		allocation: number;
		selection: number;
		interaction: number;
	}
	let attribution = $state<AttributionRow[]>([]);

	const attributionTotals = $derived.by(() => {
		if (attribution.length === 0) return null;
		return {
			allocation: attribution.reduce((s, r) => s + r.allocation, 0),
			selection: attribution.reduce((s, r) => s + r.selection, 0),
			interaction: attribution.reduce((s, r) => s + r.interaction, 0),
		};
	});

	function fmtAttr(v: number): string {
		const sign = v >= 0 ? "+" : "";
		return sign + (v * 100).toFixed(2) + "%";
	}

	function attrClass(v: number): string {
		if (v > 0) return "attr-pos";
		if (v < 0) return "attr-neg";
		return "";
	}

	function remove(id: string) {
		const index = sandboxBasket.findIndex((x) => x.instrument_id === id);
		if (index >= 0) sandboxBasket.splice(index, 1);
	}

	async function runOptimization() {
		loading = true;
		
		// SIMULATION of backend execution asyncio.to_thread() to cvxpy
		// Wait 1.5s
		await new Promise((r) => setTimeout(r, 1500));
		
		const dates = Array.from({length: 30}, (_, i) => `2025-01-${(i+1).toString().padStart(2, '0')}`);
		const curve = Array.from({length: 30}, (_, i) => 100 + i * 0.5 + Math.random() * 2);

		equityCurveOptions = {
			title: { text: "Out-of-Sample Capital Curve", textStyle: { color: "#9aa3b3", fontSize: 12 } },
			grid: { top: 40, right: 20, bottom: 20, left: 40 },
			xAxis: { type: "category", data: dates, show: false },
			yAxis: { type: "value", scale: true, splitLine: { lineStyle: { color: "#1e293b" } } },
			series: [{ type: "line", data: curve, smooth: true, itemStyle: { color: "#3b82f6" }, areaStyle: { color: "rgba(59, 130, 246, 0.1)" } }],
			backgroundColor: "transparent"
		};

		const instruments = sandboxBasket.map(b => b.ticker);
		const weights = sandboxBasket.map(() => Math.random() * maxWeight);

		weightsOptions = {
			title: { text: "Optimal Weights", textStyle: { color: "#9aa3b3", fontSize: 12 } },
			grid: { top: 30, right: 20, bottom: 20, left: 60 },
			xAxis: { type: "value", show: false },
			yAxis: { type: "category", data: instruments, axisLabel: { color: "#9aa3b3", fontSize: 10 } },
			series: [{ type: "bar", data: weights, itemStyle: { color: "#10b981" } }],
			backgroundColor: "transparent"
		};

		kpis = [
			{ label: "CAGR", value: "12.4%" },
			{ label: "Vol", value: "8.2%" },
			{ label: "Sharpe", value: "1.51" },
			{ label: "Max DD", value: "-6.4%" },
		];

		// Simulated Brinson-Fachler attribution decomposition
		attribution = sandboxBasket.map((b) => ({
			block: b.ticker,
			allocation: (Math.random() - 0.3) * 0.04,
			selection: (Math.random() - 0.4) * 0.06,
			interaction: (Math.random() - 0.5) * 0.02,
		}));

		loading = false;
	}
</script>

<div class="sandbox-root">
	<div class="sb-left">
		<div class="sb-header">
			<h1>Flight Controls</h1>
			<p>Optimization Sandbox</p>
		</div>

		<div class="sb-basket">
			<h2>Basket ({sandboxBasket.length})</h2>
			{#if sandboxBasket.length === 0}
				<div class="empty">Empty. Go to Screener to add funds.</div>
			{/if}
			{#each sandboxBasket as item (item.instrument_id)}
				<div class="basket-item">
					<span class="ticker">{item.ticker}</span>
					<button class="remove-btn" onclick={() => remove(item.instrument_id)}>[ X ]</button>
				</div>
			{/each}
		</div>

		<div class="sb-controls">
			<div class="control-group">
				<label>Solver Engine</label>
				<select bind:value={solver}>
					<option value="CLARABEL">CLARABEL (Convex)</option>
					<option value="NSGA2">NSGA-II (Heuristic)</option>
				</select>
			</div>

			<div class="control-group">
				<label>Max Weight: {maxWeight}%</label>
				<input type="range" min="1" max="100" bind:value={maxWeight} />
			</div>

			<div class="control-group">
				<label>Lookback Window: {lookbackWindow}Y</label>
				<input type="range" min="1" max="10" bind:value={lookbackWindow} />
			</div>
		</div>

		<button 
			class="action-btn" 
			class:loading={loading}
			onclick={runOptimization}
			disabled={sandboxBasket.length === 0 || loading}
		>
			{#if loading}
				[ CALCULATING FRONTIER... ]
			{:else}
				[ RUN OPTIMIZATION ]
			{/if}
		</button>
	</div>

	<div class="sb-right">
		<div class="output-top">
			{#if equityCurveOptions}
				<GenericEChart options={equityCurveOptions} />
			{:else}
				<div class="placeholder">Run optimization to see equity curve.</div>
			{/if}
		</div>
		
		<div class="output-bottom">
			<div class="output-bl">
				{#if weightsOptions}
					<GenericEChart options={weightsOptions} />
				{:else}
					<div class="placeholder">Optimal weights will appear here.</div>
				{/if}
			</div>
			
			<div class="output-br">
				<div class="output-br-inner">
					{#if kpis.length > 0}
						<table class="kpi-table">
							<tbody>
								{#each kpis as kpi}
									<tr>
										<td class="kpi-label">{kpi.label}</td>
										<td class="kpi-value">{kpi.value}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					{:else}
						<div class="placeholder">KPIs pending.</div>
					{/if}

					{#if attribution.length > 0 && attributionTotals}
						<div class="attr-section">
							<h3 class="attr-title">[ ATTRIBUTION DECOMPOSITION (BRINSON-FACHLER) ]</h3>
							<table class="attr-table">
								<thead>
									<tr>
										<th class="attr-th attr-left">Asset/Block</th>
										<th class="attr-th attr-right">Alloc Eff</th>
										<th class="attr-th attr-right">Select Eff</th>
										<th class="attr-th attr-right">Interact Eff</th>
									</tr>
								</thead>
								<tbody>
									{#each attribution as row (row.block)}
										<tr class="attr-row">
											<td class="attr-td attr-left attr-ticker">{row.block}</td>
											<td class="attr-td attr-right attr-num {attrClass(row.allocation)}">{fmtAttr(row.allocation)}</td>
											<td class="attr-td attr-right attr-num {attrClass(row.selection)}">{fmtAttr(row.selection)}</td>
											<td class="attr-td attr-right attr-num {attrClass(row.interaction)}">{fmtAttr(row.interaction)}</td>
										</tr>
									{/each}
								</tbody>
								<tfoot>
									<tr class="attr-total-row">
										<td class="attr-td attr-left attr-total-label">TOTAL</td>
										<td class="attr-td attr-right attr-num attr-total {attrClass(attributionTotals.allocation)}">{fmtAttr(attributionTotals.allocation)}</td>
										<td class="attr-td attr-right attr-num attr-total {attrClass(attributionTotals.selection)}">{fmtAttr(attributionTotals.selection)}</td>
										<td class="attr-td attr-right attr-num attr-total {attrClass(attributionTotals.interaction)}">{fmtAttr(attributionTotals.interaction)}</td>
									</tr>
								</tfoot>
							</table>
						</div>
					{/if}
				</div>
			</div>
		</div>
	</div>
</div>

<style>
	.sandbox-root {
		display: grid;
		grid-template-columns: 350px 1fr;
		height: 100vh;
		width: 100vw;
		background: #0b0f1a;
		color: #e2e8f0;
		font-family: "Urbanist", system-ui, sans-serif;
		overflow: hidden; /* No global scroll */
	}

	.sb-left {
		display: flex;
		flex-direction: column;
		border-right: 1px solid rgba(255, 255, 255, 0.1);
		padding: 24px;
		gap: 24px;
		background: #0d1220;
		overflow-y: auto;
	}

	.sb-header h1 {
		font-size: 20px;
		font-weight: 700;
		margin: 0 0 4px 0;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: #ffffff;
	}
	.sb-header p {
		font-size: 12px;
		color: #5a6577;
		margin: 0;
	}

	.sb-basket {
		display: flex;
		flex-direction: column;
		gap: 8px;
		flex: 1;
		min-height: 150px;
	}

	.sb-basket h2 {
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: #5a6577;
		margin: 0 0 8px 0;
		font-weight: 600;
	}

	.basket-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 8px 12px;
		background: rgba(255, 255, 255, 0.03);
		border-radius: 4px;
		font-size: 12px;
	}

	.ticker {
		font-weight: 700;
		font-family: monospace;
	}

	.remove-btn {
		background: transparent;
		border: none;
		color: #ef4444;
		font-size: 10px;
		font-weight: 700;
		cursor: pointer;
		font-family: monospace;
	}
	.remove-btn:hover { color: #f87171; }

	.empty {
		font-size: 12px;
		color: #5a6577;
		font-style: italic;
	}

	.sb-controls {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.control-group {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.control-group label {
		font-size: 11px;
		font-weight: 600;
		color: #9aa3b3;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	select, input[type="range"] {
		width: 100%;
		background: rgba(0,0,0,0.3);
		border: 1px solid rgba(255,255,255,0.1);
		color: white;
		padding: 6px;
		border-radius: 4px;
		font-family: monospace;
		font-size: 12px;
	}

	.action-btn {
		width: 100%;
		padding: 16px;
		background: #1e293b;
		color: #fff;
		border: 1px solid #334155;
		font-family: monospace;
		font-size: 14px;
		font-weight: 700;
		letter-spacing: 0.1em;
		cursor: pointer;
		text-transform: uppercase;
		transition: all 0.2s;
	}

	.action-btn:hover:not(:disabled) {
		background: #3b82f6;
		border-color: #60a5fa;
	}

	.action-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.action-btn.loading {
		border: 2px solid #f59e0b;
		color: #f59e0b;
		background: rgba(245, 158, 11, 0.1);
		animation: pulse 1.5s infinite;
	}

	@keyframes pulse {
		0% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.4); }
		70% { box-shadow: 0 0 0 10px rgba(245, 158, 11, 0); }
		100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); }
	}

	.sb-right {
		display: flex;
		flex-direction: column;
		height: 100%;
	}

	.output-top {
		flex: 1;
		border-bottom: 1px solid rgba(255, 255, 255, 0.1);
		padding: 24px;
		min-height: 0; /* Important for flex child */
	}

	.output-bottom {
		flex: 1;
		display: grid;
		grid-template-columns: 1fr 1fr;
		min-height: 0;
	}

	.output-bl {
		border-right: 1px solid rgba(255, 255, 255, 0.1);
		padding: 24px;
		overflow: hidden;
	}

	.output-br {
		padding: 12px 16px;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		overflow-y: auto;
	}

	.output-br-inner {
		width: 100%;
		display: flex;
		flex-direction: column;
		gap: 12px;
		align-items: center;
	}

	.placeholder {
		width: 100%;
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 14px;
		color: #5a6577;
		font-family: monospace;
		border: 1px dashed rgba(255,255,255,0.1);
	}

	.kpi-table {
		width: 100%;
		max-width: 300px;
		border-collapse: collapse;
		font-family: monospace;
		font-size: 14px;
	}

	.kpi-table td {
		padding: 6px 8px;
		border-bottom: 1px solid rgba(255,255,255,0.05);
	}

	.kpi-label {
		color: #9aa3b3;
		text-align: left;
	}

	.kpi-value {
		color: #e2e8f0;
		text-align: right;
		font-weight: 700;
	}

	/* ── Attribution Decomposition ────────────────────── */
	.attr-section {
		width: 100%;
	}

	.attr-title {
		font-family: monospace;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
		color: #5a6577;
		margin: 0 0 6px 0;
		text-transform: uppercase;
	}

	.attr-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 11px;
	}

	.attr-th {
		padding: 4px 8px;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: #5a6577;
		border-bottom: 1px solid rgba(255, 255, 255, 0.08);
		white-space: nowrap;
	}

	.attr-left { text-align: left; }
	.attr-right { text-align: right; }

	.attr-row:nth-child(even) {
		background: rgba(255, 255, 255, 0.012);
	}

	.attr-td {
		padding: 3px 8px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.03);
		white-space: nowrap;
	}

	.attr-ticker {
		font-weight: 700;
		font-family: monospace;
		color: #e2e8f0;
		font-size: 10px;
	}

	.attr-num {
		font-variant-numeric: tabular-nums;
		font-family: monospace;
		font-size: 11px;
	}

	.attr-pos { color: #22c55e; }
	.attr-neg { color: #ef4444; }

	.attr-total-row {
		border-top: 1px solid rgba(255, 255, 255, 0.12);
	}

	.attr-total-label {
		font-weight: 700;
		font-family: monospace;
		color: #9aa3b3;
		font-size: 10px;
		letter-spacing: 0.05em;
	}

	.attr-total {
		font-weight: 700;
	}
</style>
