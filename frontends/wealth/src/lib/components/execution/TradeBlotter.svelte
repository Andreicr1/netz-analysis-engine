<script lang="ts">
	import type { InstrumentWeight } from "$lib/types/model-portfolio";

	export interface HoldingWeight {
		instrument_id: string;
		fund_name: string;
		weight: number;
	}

	interface Props {
		currentWeights: HoldingWeight[];
		optimalWeights: InstrumentWeight[];
	}

	let { currentWeights, optimalWeights }: Props = $props();

	let targetAUM = $state<number>(1000000);

	const orders = $derived.by(() => {
		const currentMap = new Map(currentWeights.map(w => [w.instrument_id, w]));
		const optimalMap = new Map(optimalWeights.map(w => [w.instrument_id, w]));
		
		const allIds = new Set([...currentMap.keys(), ...optimalMap.keys()]);
		
		const result = [];
		for (const id of allIds) {
			const current = currentMap.get(id)?.weight || 0;
			const optimal = optimalMap.get(id)?.weight || 0;
			const fundName = optimalMap.get(id)?.fund_name || currentMap.get(id)?.fund_name || "UNKNOWN";
			
			const drift = optimal - current;
			
			if (Math.abs(drift) > 0.001) {
				const orderValue = drift * targetAUM;
				result.push({
					ticker: fundName,
					action: drift > 0 ? "BUY" : "SELL",
					drift,
					orderValue
				});
			}
		}
		
		// Sort: BUY first, then SELL, then by absolute value
		return result.sort((a, b) => b.drift - a.drift);
	});

	function handleRouteToOms() {
		console.log("Routing to OMS: ", JSON.stringify(orders, null, 2));
	}

	function formatValue(val: number) {
		return Math.abs(val).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	}

	function formatDelta(val: number) {
		const sign = val > 0 ? "+" : "";
		return sign + (val * 100).toFixed(2) + "%";
	}
</script>

<div class="blotter-root">
	<div class="blotter-header">
		<label class="aum-label">
			<span>TARGET AUM ($)</span>
			<input type="number" bind:value={targetAUM} class="aum-input" />
		</label>
	</div>

	<div class="blotter-table-wrapper">
		<table class="blotter-table">
			<thead>
				<tr>
					<th>TICKER</th>
					<th>ACTION</th>
					<th class="num">DELTA</th>
					<th class="num">EST. VALUE</th>
				</tr>
			</thead>
			<tbody>
				{#each orders as order}
					<tr>
						<td>{order.ticker}</td>
						<td>
							{#if order.action === "BUY"}
								<span class="text-[#22c55e] font-bold">[ BUY ]</span>
							{:else}
								<span class="text-[#ef4444] font-bold">[ SELL ]</span>
							{/if}
						</td>
						<td class="num tabular-nums">{formatDelta(order.drift)}</td>
						<td class="num tabular-nums">$ {formatValue(order.orderValue)}</td>
					</tr>
				{/each}
				{#if orders.length === 0}
					<tr>
						<td colspan="4" class="empty-msg">No actionable drift detected.</td>
					</tr>
				{/if}
			</tbody>
		</table>
	</div>

	<button 
		class="route-btn {orders.length > 0 ? 'active' : 'inactive'}"
		onclick={handleRouteToOms}
		disabled={orders.length === 0}
	>
		[ ROUTE TO OMS ]
	</button>
</div>

<style>
	.blotter-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		background-color: #0b0f1a;
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
		font-size: 11px;
		color: #e5e7eb;
	}

	.blotter-header {
		padding: 12px;
		border-bottom: 1px solid #333;
		background-color: #000;
	}

	.aum-label {
		display: flex;
		justify-content: space-between;
		align-items: center;
		color: #9ca3af;
		font-weight: 700;
	}

	.aum-input {
		background: #000;
		border: 1px solid #333;
		color: #fff;
		padding: 4px 8px;
		text-align: right;
		width: 120px;
		font-family: inherit;
		font-size: 11px;
	}
	
	.aum-input:focus {
		outline: none;
		border-color: #2d7ef7;
	}

	.blotter-table-wrapper {
		flex: 1;
		overflow-y: auto;
		padding: 4px;
	}

	.blotter-table {
		width: 100%;
		border-collapse: collapse;
	}

	.blotter-table th, .blotter-table td {
		padding: 6px 8px;
		border-bottom: 1px solid #1a1f2e;
		text-align: left;
	}

	.blotter-table th {
		color: #5a6577;
		font-weight: normal;
	}

	.blotter-table .num {
		text-align: right;
	}

	.tabular-nums {
		font-variant-numeric: tabular-nums;
	}

	.empty-msg {
		text-align: center;
		color: #5a6577;
		padding: 24px !important;
	}

	.route-btn {
		width: 100%;
		padding: 12px;
		font-weight: 700;
		font-family: inherit;
		border: none;
		cursor: pointer;
		text-align: center;
		transition: all 0.2s;
	}

	.route-btn.active {
		background-color: #2563eb; /* bg-blue-600 */
		color: #fff;
	}
	.route-btn.active:hover {
		background-color: #1d4ed8;
	}

	.route-btn.inactive {
		background-color: #374151; /* gray metallic */
		color: #9ca3af;
		cursor: not-allowed;
	}
</style>
