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
		gap: 1px;
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
	}
	.ep-header,
	.ep-loading,
	.ep-empty {
		padding: var(--terminal-space-2) var(--terminal-space-3);
	}
	.ep-title {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
	}
	.ep-loading,
	.ep-empty {
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
	}
	.ep-table-header,
	.ep-row {
		display: grid;
		grid-template-columns: 1fr 54px 54px 54px 40px;
		padding: 2px var(--terminal-space-2);
	}
	.ep-table-header {
		background: var(--terminal-bg-panel-sunken);
		color: var(--terminal-fg-tertiary);
		font-size: 9px;
		letter-spacing: 0.05em;
	}
	.ep-row {
		color: var(--terminal-fg-secondary);
		font-size: var(--terminal-text-10);
	}
	.ep-row:hover {
		background: var(--terminal-bg-panel-raised);
	}
	.ep-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.ep-period,
	.ep-consensus {
		color: var(--terminal-fg-tertiary);
	}
	.ep-actual,
	.ep-consensus {
		font-variant-numeric: tabular-nums;
	}
	.ep-actual {
		color: var(--terminal-fg-primary);
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
