<script lang="ts">
	export interface EconRow {
		name: string;
		period: string;
		actual: number | null;
		consensus: number | null;
		unit: string;
		surprise: number;
	}

	interface Props {
		rows: EconRow[];
		loading?: boolean;
	}

	let { rows, loading = false }: Props = $props();

	function surpriseIcon(surprise: number): string {
		if (surprise > 0.5) return "UP";
		if (surprise < -0.5) return "DN";
		return "-";
	}

	function surpriseColor(surprise: number): string {
		if (surprise > 0.5) return "var(--terminal-accent-green, #4adf86)";
		if (surprise < -0.5) return "var(--terminal-accent-red, #f87171)";
		return "var(--terminal-fg-tertiary)";
	}

	function fmt(value: number | null, unit: string): string {
		if (value === null) return "-";
		return unit === "%" ? `${value.toFixed(1)}%` : value.toFixed(1);
	}
</script>

<div class="ep-root">
	<div class="ep-header"><span class="ep-title">ECON PULSE</span></div>

	{#if loading}
		<div class="ep-loading">LOADING...</div>
	{:else if rows.length === 0}
		<div class="ep-empty">No data available</div>
	{:else}
		<div class="ep-table-header">
			<span>INDICATOR</span>
			<span>PERIOD</span>
			<span class="ep-right">ACTUAL</span>
			<span class="ep-right">CONS.</span>
			<span class="ep-center">SRPS</span>
		</div>
		{#each rows as row (row.name)}
			<div class="ep-row">
				<span class="ep-name">{row.name}</span>
				<span class="ep-period">{row.period}</span>
				<span class="ep-right ep-actual">{fmt(row.actual, row.unit)}</span>
				<span class="ep-right ep-consensus">{fmt(row.consensus, row.unit)}</span>
				<span class="ep-center ep-surprise" style:color={surpriseColor(row.surprise)}>{surpriseIcon(row.surprise)}</span>
			</div>
		{/each}
	{/if}
</div>

<style>
	.ep-root {
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
		background: var(--ii-surface);
		font-family: var(--ii-font-mono);
	}
	.ep-header,
	.ep-loading,
	.ep-empty {
		padding: 10px 14px 8px;
	}
	.ep-title {
		color: var(--ii-text-primary);
		font-size: 12px;
		font-weight: 700;
		letter-spacing: 0.14em;
	}
	.ep-loading,
	.ep-empty {
		color: var(--ii-text-muted);
		font-size: 10px;
	}
	.ep-table-header,
	.ep-row {
		display: grid;
		grid-template-columns: 1fr 64px 64px 64px 44px;
		padding: 4px 14px;
	}
	.ep-table-header {
		background: var(--ii-bg);
		color: var(--ii-text-muted);
		font-size: 9px;
		letter-spacing: 0.05em;
	}
	.ep-row {
		border-top: 1px solid var(--ii-terminal-hair);
		color: var(--ii-text-secondary);
		font-size: 10px;
	}
	.ep-row:hover {
		background: var(--ii-surface-alt);
	}
	.ep-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.ep-period,
	.ep-consensus {
		color: var(--ii-text-muted);
	}
	.ep-actual,
	.ep-consensus {
		font-variant-numeric: tabular-nums;
	}
	.ep-actual {
		color: var(--ii-text-primary);
	}
	.ep-surprise {
		font-size: 9px;
		font-weight: 700;
	}
	.ep-right {
		text-align: right;
	}
	.ep-center {
		text-align: center;
	}
</style>
